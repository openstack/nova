#!/usr/bin/env python3
# Copyright 2025 Red Hat
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import argparse
import collections
import logging
import socket
import subprocess
import threading
import time

from keystoneauth1 import exceptions
from keystoneauth1 import loading
from openstack import connection
from oslo_concurrency import lockutils
from oslo_config import cfg
import oslo_messaging
from oslo_serialization import jsonutils

LOG = logging.getLogger('cleaner')
loading.register_session_conf_options(cfg.CONF, 'placement')  # noqa
loading.register_auth_conf_options(cfg.CONF, 'placement')  # noqa
loading.register_adapter_conf_options(cfg.CONF, 'placement')  # noqa
cfg.CONF.register_opts([cfg.StrOpt('host')])  # noqa


def link_for_rp(rp, linktype):
    """Return the URL for a named link relation"""
    for link in rp.links:
        if link['rel'] == linktype:
            # This link will have the full path as used to access it,
            # but keystoneauth will re-add the baseurl (i.e. /placement
            # to it)
            return link['href'].split('/', 2)[2]


def periodic_thread(cleaner, delay):
    while True:
        time.sleep(delay)
        LOG.info('Running periodic clean')
        try:
            cleaner.trigger()
        except Exception as e:
            LOG.exception('Failed to run periodic cleaning: %s', e)


class CleaningEndpoint:
    """A notification listener endpoint that triggers cleaner on delete."""
    filter_rule = oslo_messaging.NotificationFilter(
        event_type=r'instance\.delete\.end$')

    def __init__(self, cleaner, publisher_filter):
        self.cleaner = cleaner
        self.publisher_filter = publisher_filter

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        if publisher_id == self.publisher_filter:
            LOG.info('Instance deleted on %s', publisher_id)
            self.cleaner.trigger()
        else:
            LOG.debug('Ignoring notification from %s != %s',
                      publisher_id, self.publisher_filter)

    audit = info
    debug = info
    warn = info
    error = info
    critical = info
    sample = info


class Cleaner:
    """Base class for a cleaner for a given device type"""

    def match(self, pci_addr):
        """Determine if a PCI device matches this type"""
        return False

    def clean(self, rp, pci_addr):
        """Clean a specific device"""
        raise NotImplementedError()


class GenericCleaner(Cleaner):
    def match(self, pci_addr):
        return True

    def clean(self, rp, pci_addr):
        cmd = [self.CMD, pci_addr, rp.id]
        LOG.debug('Running %r', ' '.join(cmd))
        subprocess.check_call(cmd)

    @classmethod
    def for_command(cls, cmd):
        class CommandCleaner(cls):
            CMD = cmd

        return CommandCleaner


class NVMECleaner(Cleaner):
    def __init__(self):
        output = subprocess.check_output('nvme list -v -o json', shell=True)
        data = jsonutils.loads(output)
        self._nvmes = collections.defaultdict(list)
        for device in data['Devices']:
            for controller in device['Controllers']:
                for ns in controller['Namespaces']:
                    self._nvmes[controller['Address']].append(ns['NameSpace'])
        LOG.debug('Found NVMe devices: %s', self._nvmes)

    def match(self, pci_addr):
        return pci_addr in self._nvmes

    def clean(self, rp, pci_addr):
        devices = self._nvmes[pci_addr]
        # NOTE(danms): This may not be good enough (we may need to use the
        # "sanitize" option), or we may need to provide more options based
        # on what the NVMe supports.
        LOG.info('Cleaning %s', ','.join(devices))
        for nsdev in devices:
            cmd = 'nvme format -f -s1 /dev/%s' % nsdev
            LOG.debug('Running %r to clean %s (%s %s)', cmd, nsdev,
                      rp.id, pci_addr)
            subprocess.check_call(cmd, shell=True)


class CleaningWatcher():
    def __init__(self, client, rp_name, cleaners, dry_run=False):
        self.client = client
        self.endpoint = CleaningEndpoint(self, 'nova-compute:%s' % rp_name)
        self.rp = client.find_resource_provider(rp_name)
        self.cleaners = cleaners
        self.dryrun = dry_run

    def _getjson(self, url):
        return self.client.session.get(
            url, microversion='1.6',
            endpoint_filter={'service_type': 'placement'}).json()

    def _putjson(self, url, data):
        return self.client.session.put(
            url, json=data, microversion='1.6',
            endpoint_filter={'service_type': 'placement'})

    def traits_for_rp(self, rp):
        # NOTE(danms): openstacksdk has no support for resource provider
        # traits, so query directly here.
        url = link_for_rp(rp, 'traits')
        return self._getjson(url)['traits']

    def allocations_for_rp(self, rp):
        # NOTE(danms): openstacksdk has no support for resource provider
        # allocations, so query directly here.
        url = link_for_rp(rp, 'allocations')
        return self._getjson(url)['allocations']

    def rp_inventory_to_clean(self, rp):
        inventory = list(self.client.resource_provider_inventories(rp))
        if len(inventory) != 1:
            # This has OTU traitage, but doesn't look like a PCI-in-placement
            # provider, so skip it for safety.
            LOG.warning(
                'Skipping provider %s because it has %i inventories',
                rp.id, len(inventory))
            return
        # OTU devices are "burned" when they have reserved == total
        is_reserved = inventory[0].reserved == inventory[0].total
        allocs = self.allocations_for_rp(rp)
        LOG.debug('Allocations for %s: %s', rp.id, allocs)
        LOG.debug('Inventory for %s: %s', rp.id, inventory)
        # A provider needs cleaning if it is reserved and has no allocations
        if is_reserved and not allocs:
            return inventory[0]

    def pci_addr_for_rp(self, rp):
        # This format is defined in the PCI-in-placement work as:
        # hostname_DDDD:BB:SS.FF
        host, addr = rp.name.split('_')
        return addr

    def unreserve(self, inventory):
        LOG.info('Unreserving %s on %s', inventory.resource_class,
                 inventory.resource_provider_id)
        # NOTE(danms): openstacksdk apparently can't change *just* reserved
        # for a provider inventory. Placement requires total be in the payload,
        # which the sdk will not include if it thinks it is unchanged. So,
        # manually PUT the inventory here.
        url = '/'.join([
            inventory.base_path % {
                'resource_provider_id': inventory.resource_provider_id},
            inventory.resource_class])
        inventory = {
            'resource_provider_generation': (
                inventory.resource_provider_generation),
            'reserved': 0,
            'total': inventory.total,
        }

        r = self._putjson(url, inventory)
        r.raise_for_status()

    def run_cleaner(self, rp, pci_addr, cleaner, inventory):
        if self.dryrun:
            LOG.info('Would use %s to clean %s %s',
                     cleaner.__class__.__name__,
                     inventory.resource_provider_id,
                     inventory.resource_class)
            return
        try:
            cleaner.clean(rp, pci_addr)
            self.unreserve(inventory)
        except subprocess.CalledProcessError as e:
            LOG.error('Failed to clean %s (%s) - action returned %i',
                      pci_addr, rp.id, e.returncode)
        except exceptions.HttpError as e:
            LOG.error('Failed to unreserve %s: %s', rp.id, e)
        except Exception as e:
            LOG.exception('Unexpected error cleaning %s (%s): %s',
                          pci_addr, rp.id, e)

    @lockutils.synchronized('cleaner')
    def trigger(self):
        children = self.client.resource_providers(in_tree=self.rp.id)
        children = list(children)
        cleaners = [cleaner_cls() for cleaner_cls in self.cleaners]
        for child in children:
            is_otu = 'HW_PCI_ONE_TIME_USE' in self.traits_for_rp(child)
            inventory_to_clean = self.rp_inventory_to_clean(child)
            needs_cleaning = is_otu and inventory_to_clean
            LOG.debug('Provider %s needs cleaning: %s (otu=%s)',
                      child.id, needs_cleaning, is_otu)
            if not needs_cleaning:
                continue
            pci_addr = self.pci_addr_for_rp(child)
            matched_cleaners = [cleaner for cleaner in cleaners
                                if cleaner.match(pci_addr)]
            for cleaner in matched_cleaners:
                self.run_cleaner(child, pci_addr, cleaner, inventory_to_clean)
            if not matched_cleaners and needs_cleaning:
                # Unsupported device type, don't clean
                LOG.warning('Child provider %s for %s needs cleaning but no '
                            'cleaning implementations matched!',
                             child.id, pci_addr)


class LoggerEndpoint:
    """A notification endpoint that just logs each event received for debug"""

    def info(self, ctxt, publisher_id, event_type, payload, metadata):
        LOG.info('Event: %s %s', publisher_id, event_type)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--topic', default=None,
                   help=('Notification queue. Defaults to '
                         'notifications-$provider_name for recommended '
                         'per-compute topic configuration'))
    p.add_argument('--debug', action='store_true',
                   help='Enable verbose debug logging')
    p.add_argument('--provider-name', default=None,
                   help=('Parent provider name for this compute node '
                         '(if unspecified, attempt to detect)'))
    p.add_argument('--one', action='store_true',
                   help='Run one cleaning pass and exit')
    p.add_argument('--dry-run', action='store_true',
                   help='Do not actually clean, just print what would be done')
    p.add_argument('--pool', default=None,
                   help=('oslo.messaging receiver pool name (see caveats '
                         'about this usage)'))
    p.add_argument('--periodic', type=int, default=0,
                   help='Scan for missed required cleaning every N minutes')
    p.add_argument('--nvme', action='store_true',
                   help=('Clean NVMe devices with `nvme format` on all '
                         'namespaces'))
    p.add_argument('--generic-cmd',
                   help=('Run this command for each PCI device needing to be '
                         'cleaned. Arguments are "pci_addr rp_uuid"'))
    args = p.parse_args()
    cfg.CONF([], project='nova')

    auth = loading.load_auth_from_conf_options(cfg.CONF, 'placement')
    sess = loading.load_session_from_conf_options(cfg.CONF, 'placement',
                                                  auth=auth)
    placement = connection.Connection(session=sess,
                                      oslo_conf=cfg.CONF).placement

    logging.basicConfig(level=args.debug and logging.DEBUG or logging.INFO)

    if not args.provider_name:
        if cfg.CONF.host:
            args.provider_name = cfg.CONF.host
        else:
            args.provider_name = socket.gethostname().split('.')[0]
    if not args.topic:
        args.topic = 'notifications-%s' % args.provider_name

    # This could be dynamic based on arguments to control what things we do
    cleaners = []
    if args.nvme:
        cleaners.append(NVMECleaner)
    if args.generic_cmd:
        cleaners.append(GenericCleaner.for_command(args.generic_cmd))
    if len(cleaners) > 1:
        # NOTE(danms): This should be supportable, but it complicates our
        # "when to unreserve" logic, so just keep this simple at the moment.
        print('Only one type of cleaner may be enabled at a time')
        return 1
    c = CleaningWatcher(placement, args.provider_name, cleaners,
                        dry_run=args.dry_run)
    # Trigger at least once at startup before we potentially start processing
    # notifications
    c.trigger()

    if args.one:
        return

    if args.periodic:
        periodic = threading.Thread(target=periodic_thread,
                                    args=(c, args.periodic * 60))
        periodic.daemon = True
        periodic.start()

    transport = oslo_messaging.get_notification_transport(cfg.CONF)
    targets = [oslo_messaging.Target(topic=args.topic, exchange='nova')]
    endpoints = [c.endpoint]
    if args.debug:
        endpoints.insert(0, LoggerEndpoint())

    server = oslo_messaging.get_notification_listener(transport, targets,
                                                      endpoints,
                                                      pool=args.pool)
    server.start()
    try:
        server.wait()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
