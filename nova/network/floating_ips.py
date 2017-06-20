# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from oslo_concurrency import processutils
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import uuidutils
import six

import nova.conf
from nova import context
from nova.db import base
from nova import exception
from nova.i18n import _LE, _LI, _LW
from nova.network import rpcapi as network_rpcapi
from nova import objects
from nova import rpc
from nova import servicegroup
from nova import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class FloatingIP(object):
    """Mixin class for adding floating IP functionality to a manager."""

    servicegroup_api = None

    def init_host_floating_ips(self):
        """Configures floating IPs owned by host."""

        admin_context = context.get_admin_context()
        try:
            floating_ips = objects.FloatingIPList.get_by_host(admin_context,
                                                              self.host)
        except exception.NotFound:
            return

        for floating_ip in floating_ips:
            if floating_ip.fixed_ip_id:
                try:
                    fixed_ip = floating_ip.fixed_ip
                except exception.FixedIpNotFound:
                    LOG.debug('Fixed IP %s not found', floating_ip.fixed_ip_id)
                    continue
                interface = CONF.public_interface or floating_ip.interface
                try:
                    self.l3driver.add_floating_ip(floating_ip.address,
                                                  fixed_ip.address,
                                                  interface,
                                                  fixed_ip.network)
                except processutils.ProcessExecutionError:
                    LOG.debug('Interface %s not found', interface)
                    raise exception.NoFloatingIpInterface(interface=interface)

    def allocate_for_instance(self, context, **kwargs):
        """Handles allocating the floating IP resources for an instance.

        calls super class allocate_for_instance() as well

        rpc.called by network_api
        """
        instance_uuid = kwargs.get('instance_id')
        if not uuidutils.is_uuid_like(instance_uuid):
            instance_uuid = kwargs.get('instance_uuid')
        project_id = kwargs.get('project_id')
        # call the next inherited class's allocate_for_instance()
        # which is currently the NetworkManager version
        # do this first so fixed ip is already allocated
        nw_info = super(FloatingIP, self).allocate_for_instance(context,
                                                                **kwargs)
        if CONF.auto_assign_floating_ip:
            context = context.elevated()
            # allocate a floating ip
            floating_address = self.allocate_floating_ip(context, project_id,
                True)
            LOG.debug("floating IP allocation for instance "
                      "|%s|", floating_address,
                      instance_uuid=instance_uuid)

            # get the first fixed address belonging to the instance
            fixed_ips = nw_info.fixed_ips()
            fixed_address = fixed_ips[0]['address']

            # associate the floating ip to fixed_ip
            self.associate_floating_ip(context,
                                       floating_address,
                                       fixed_address,
                                       affect_auto_assigned=True)

            # create a fresh set of network info that contains the floating ip
            nw_info = self.get_instance_nw_info(context, **kwargs)

        return nw_info

    def deallocate_for_instance(self, context, **kwargs):
        """Handles deallocating floating IP resources for an instance.

        calls super class deallocate_for_instance() as well.

        rpc.called by network_api
        """
        if 'instance' in kwargs:
            instance_uuid = kwargs['instance'].uuid
        else:
            instance_uuid = kwargs['instance_id']
            if not uuidutils.is_uuid_like(instance_uuid):
                # NOTE(francois.charlier): in some cases the instance might be
                # deleted before the IPs are released, so we need to get
                # deleted instances too
                instance = objects.Instance.get_by_id(
                    context.elevated(read_deleted='yes'), instance_uuid)
                instance_uuid = instance.uuid

        try:
            fixed_ips = objects.FixedIPList.get_by_instance_uuid(
                context, instance_uuid)
        except exception.FixedIpNotFoundForInstance:
            fixed_ips = []
        # add to kwargs so we can pass to super to save a db lookup there
        kwargs['fixed_ips'] = fixed_ips
        for fixed_ip in fixed_ips:
            fixed_id = fixed_ip.id
            floating_ips = objects.FloatingIPList.get_by_fixed_ip_id(context,
                                                                     fixed_id)
            # disassociate floating ips related to fixed_ip
            for floating_ip in floating_ips:
                address = str(floating_ip.address)
                try:
                    self.disassociate_floating_ip(context,
                                                  address,
                                                  affect_auto_assigned=True)
                except exception.FloatingIpNotAssociated:
                    LOG.info(_LI("Floating IP %s is not associated. Ignore."),
                             address)
                # deallocate if auto_assigned
                if floating_ip.auto_assigned:
                    self.deallocate_floating_ip(context, address,
                                                affect_auto_assigned=True)

        # call the next inherited class's deallocate_for_instance()
        # which is currently the NetworkManager version
        # call this after so floating IPs are handled first
        super(FloatingIP, self).deallocate_for_instance(context, **kwargs)

    def _floating_ip_owned_by_project(self, context, floating_ip):
        """Raises if floating IP does not belong to project."""
        if context.is_admin:
            return

        if floating_ip.project_id != context.project_id:
            if floating_ip.project_id is None:
                LOG.warning(_LW('Address |%(address)s| is not allocated'),
                            {'address': floating_ip.address})
                raise exception.Forbidden()
            else:
                LOG.warning(_LW('Address |%(address)s| is not allocated '
                                'to your project |%(project)s|'),
                            {'address': floating_ip.address,
                             'project': context.project_id})
                raise exception.Forbidden()

    def _floating_ip_pool_exists(self, context, name):
        """Returns true if the specified floating IP pool exists. Otherwise,
        returns false.
        """
        pools = [pool.get('name') for pool in
                 self.get_floating_ip_pools(context)]
        if name in pools:
            return True

        return False

    def allocate_floating_ip(self, context, project_id, auto_assigned=False,
                             pool=None):
        """Gets a floating IP from the pool."""
        # NOTE(tr3buchet): all network hosts in zone now use the same pool
        pool = pool or CONF.default_floating_pool
        use_quota = not auto_assigned

        if not self._floating_ip_pool_exists(context, pool):
            raise exception.FloatingIpPoolNotFound()

        # Check the quota; can't put this in the API because we get
        # called into from other places
        try:
            if use_quota:
                objects.Quotas.check_deltas(context, {'floating_ips': 1},
                                            project_id)
        except exception.OverQuota:
            LOG.warning(_LW("Quota exceeded for %s, tried to allocate "
                            "floating IP"), context.project_id)
            raise exception.FloatingIpLimitExceeded()

        floating_ip = objects.FloatingIP.allocate_address(
            context, project_id, pool, auto_assigned=auto_assigned)

        # NOTE(melwitt): We recheck the quota after creating the object to
        # prevent users from allocating more resources than their allowed quota
        # in the event of a race. This is configurable because it can be
        # expensive if strict quota limits are not required in a deployment.
        if CONF.quota.recheck_quota and use_quota:
            try:
                objects.Quotas.check_deltas(context, {'floating_ips': 0},
                                            project_id)
            except exception.OverQuota:
                objects.FloatingIP.deallocate(context, floating_ip.address)
                LOG.warning(_LW("Quota exceeded for %s, tried to allocate "
                                "floating IP"), context.project_id)
                raise exception.FloatingIpLimitExceeded()

        payload = dict(project_id=project_id, floating_ip=floating_ip)
        self.notifier.info(context,
                           'network.floating_ip.allocate', payload)

        return floating_ip

    @messaging.expected_exceptions(exception.FloatingIpNotFoundForAddress)
    def deallocate_floating_ip(self, context, address,
                               affect_auto_assigned=False):
        """Returns a floating IP to the pool."""
        floating_ip = objects.FloatingIP.get_by_address(context, address)

        # handle auto_assigned
        if not affect_auto_assigned and floating_ip.auto_assigned:
            return

        # make sure project owns this floating ip (allocated)
        self._floating_ip_owned_by_project(context, floating_ip)

        # make sure floating ip is not associated
        if floating_ip.fixed_ip_id:
            floating_address = floating_ip.address
            raise exception.FloatingIpAssociated(address=floating_address)

        # clean up any associated DNS entries
        self._delete_all_entries_for_ip(context,
                                        floating_ip.address)
        payload = dict(project_id=floating_ip.project_id,
                       floating_ip=str(floating_ip.address))
        self.notifier.info(context, 'network.floating_ip.deallocate', payload)

        objects.FloatingIP.deallocate(context, address)

    @messaging.expected_exceptions(exception.FloatingIpNotFoundForAddress)
    def associate_floating_ip(self, context, floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associates a floating IP with a fixed IP.

        Makes sure everything makes sense then calls _associate_floating_ip,
        rpc'ing to correct host if i'm not it.

        Access to the floating_address is verified but access to the
        fixed_address is not verified. This assumes that the calling
        side has already verified that the fixed_address is legal by
        checking access to the instance.
        """
        floating_ip = objects.FloatingIP.get_by_address(context,
                                                        floating_address)
        # handle auto_assigned
        if not affect_auto_assigned and floating_ip.auto_assigned:
            return

        # make sure project owns this floating ip (allocated)
        self._floating_ip_owned_by_project(context, floating_ip)

        # disassociate any already associated
        orig_instance_uuid = None
        if floating_ip.fixed_ip_id:
            # find previously associated instance
            fixed_ip = floating_ip.fixed_ip
            if str(fixed_ip.address) == fixed_address:
                # NOTE(vish): already associated to this address
                return
            orig_instance_uuid = fixed_ip.instance_uuid

            self.disassociate_floating_ip(context, floating_address)

        fixed_ip = objects.FixedIP.get_by_address(context, fixed_address)

        # send to correct host, unless i'm the correct host
        network = objects.Network.get_by_id(context.elevated(),
                                            fixed_ip.network_id)
        if network.multi_host:
            instance = objects.Instance.get_by_uuid(
                context, fixed_ip.instance_uuid)
            host = instance.host
        else:
            host = network.host

        interface = floating_ip.interface
        if host == self.host:
            # i'm the correct host
            self._associate_floating_ip(context, floating_address,
                                        fixed_address, interface,
                                        fixed_ip.instance_uuid)
        else:
            # send to correct host
            self.network_rpcapi._associate_floating_ip(context,
                    floating_address, fixed_address, interface, host,
                    fixed_ip.instance_uuid)

        return orig_instance_uuid

    def _associate_floating_ip(self, context, floating_address, fixed_address,
                               interface, instance_uuid):
        """Performs db and driver calls to associate floating IP & fixed IP."""
        interface = CONF.public_interface or interface

        @utils.synchronized(six.text_type(floating_address))
        def do_associate():
            # associate floating ip
            floating = objects.FloatingIP.associate(context, floating_address,
                                                    fixed_address, self.host)
            fixed = floating.fixed_ip
            if not fixed:
                # NOTE(vish): ip was already associated
                return
            try:
                # gogo driver time
                self.l3driver.add_floating_ip(floating_address, fixed_address,
                        interface, fixed['network'])
            except processutils.ProcessExecutionError as e:
                with excutils.save_and_reraise_exception():
                    try:
                        objects.FloatingIP.disassociate(context,
                                                        floating_address)
                    except Exception:
                        LOG.warning(_LW('Failed to disassociated floating '
                                        'address: %s'), floating_address)
                        pass
                    if "Cannot find device" in six.text_type(e):
                        try:
                            LOG.error(_LE('Interface %s not found'), interface)
                        except Exception:
                            pass
                        raise exception.NoFloatingIpInterface(
                                interface=interface)

            payload = dict(project_id=context.project_id,
                           instance_id=instance_uuid,
                           floating_ip=floating_address)
            self.notifier.info(context,
                               'network.floating_ip.associate', payload)
        do_associate()

    @messaging.expected_exceptions(exception.FloatingIpNotFoundForAddress)
    def disassociate_floating_ip(self, context, address,
                                 affect_auto_assigned=False):
        """Disassociates a floating IP from its fixed IP.

        Makes sure everything makes sense then calls _disassociate_floating_ip,
        rpc'ing to correct host if i'm not it.
        """
        floating_ip = objects.FloatingIP.get_by_address(context, address)

        # handle auto assigned
        if not affect_auto_assigned and floating_ip.auto_assigned:
            raise exception.CannotDisassociateAutoAssignedFloatingIP()

        # make sure project owns this floating ip (allocated)
        self._floating_ip_owned_by_project(context, floating_ip)

        # make sure floating ip is associated
        if not floating_ip.fixed_ip_id:
            floating_address = floating_ip.address
            raise exception.FloatingIpNotAssociated(address=floating_address)

        fixed_ip = objects.FixedIP.get_by_id(context, floating_ip.fixed_ip_id)

        # send to correct host, unless i'm the correct host
        network = objects.Network.get_by_id(context.elevated(),
                                            fixed_ip.network_id)
        interface = floating_ip.interface
        if network.multi_host:
            instance = objects.Instance.get_by_uuid(
                context, fixed_ip.instance_uuid)
            service = objects.Service.get_by_host_and_binary(
                context.elevated(), instance.host, 'nova-network')
            if service and self.servicegroup_api.service_is_up(service):
                host = instance.host
            else:
                # NOTE(vish): if the service is down just deallocate the data
                #             locally. Set the host to local so the call will
                #             not go over rpc and set interface to None so the
                #             teardown in the driver does not happen.
                host = self.host
                interface = None
        else:
            host = network.host

        if host == self.host:
            # i'm the correct host
            self._disassociate_floating_ip(context, address, interface,
                                           fixed_ip.instance_uuid)
        else:
            # send to correct host
            self.network_rpcapi._disassociate_floating_ip(context, address,
                    interface, host, fixed_ip.instance_uuid)

    def _disassociate_floating_ip(self, context, address, interface,
                                  instance_uuid):
        """Performs db and driver calls to disassociate floating IP."""
        interface = CONF.public_interface or interface

        @utils.synchronized(six.text_type(address))
        def do_disassociate():
            # NOTE(vish): Note that we are disassociating in the db before we
            #             actually remove the ip address on the host. We are
            #             safe from races on this host due to the decorator,
            #             but another host might grab the ip right away. We
            #             don't worry about this case because the minuscule
            #             window where the ip is on both hosts shouldn't cause
            #             any problems.
            floating = objects.FloatingIP.disassociate(context, address)
            fixed = floating.fixed_ip
            if not fixed:
                # NOTE(vish): ip was already disassociated
                return
            if interface:
                # go go driver time
                self.l3driver.remove_floating_ip(address, fixed.address,
                                                 interface, fixed.network)
            payload = dict(project_id=context.project_id,
                           instance_id=instance_uuid,
                           floating_ip=address)
            self.notifier.info(context,
                               'network.floating_ip.disassociate', payload)
        do_disassociate()

    @messaging.expected_exceptions(exception.FloatingIpNotFound)
    def get_floating_ip(self, context, id):
        """Returns a floating IP as a dict."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi.
        return dict(objects.FloatingIP.get_by_id(context, id))

    def get_floating_pools(self, context):
        """Returns list of floating pools."""
        # NOTE(maurosr) This method should be removed in future, replaced by
        # get_floating_ip_pools. See bug #1091668
        return self.get_floating_ip_pools(context)

    def get_floating_ip_pools(self, context):
        """Returns list of floating ip pools."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi.
        pools = objects.FloatingIP.get_pool_names(context)
        return [dict(name=name) for name in pools]

    def get_floating_ip_by_address(self, context, address):
        """Returns a floating IP as a dict."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi.
        return objects.FloatingIP.get_by_address(context, address)

    def get_floating_ips_by_project(self, context):
        """Returns the floating IPs allocated to a project."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi.
        return objects.FloatingIPList.get_by_project(context,
                                                     context.project_id)

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        """Returns the floating IPs associated with a fixed_address."""
        # NOTE(vish): This is no longer used but can't be removed until
        #             we major version the network_rpcapi.
        floating_ips = objects.FloatingIPList.get_by_fixed_address(
            context, fixed_address)
        return [str(floating_ip.address) for floating_ip in floating_ips]

    def _is_stale_floating_ip_address(self, context, floating_ip):
        try:
            self._floating_ip_owned_by_project(context, floating_ip)
        except exception.Forbidden:
            return True
        return False if floating_ip.get('fixed_ip_id') else True

    def migrate_instance_start(self, context, instance_uuid,
                               floating_addresses,
                               rxtx_factor=None, project_id=None,
                               source=None, dest=None):
        # We only care if floating_addresses are provided and we're
        # switching hosts
        if not floating_addresses or (source and source == dest):
            return

        LOG.info(_LI("Starting migration network for instance %s"),
                 instance_uuid)
        for address in floating_addresses:
            floating_ip = objects.FloatingIP.get_by_address(context, address)

            if self._is_stale_floating_ip_address(context, floating_ip):
                LOG.warning(_LW("Floating IP address |%(address)s| no longer "
                                "belongs to instance %(instance_uuid)s. "
                                "Will not migrate it "),
                            {'address': address,
                             'instance_uuid': instance_uuid})
                continue

            interface = CONF.public_interface or floating_ip.interface
            fixed_ip = floating_ip.fixed_ip
            self.l3driver.remove_floating_ip(floating_ip.address,
                                             fixed_ip.address,
                                             interface,
                                             fixed_ip.network)

            # NOTE(wenjianhn): Make this address will not be bound to public
            # interface when restarts nova-network on dest compute node
            floating_ip.host = None
            floating_ip.save()

    def migrate_instance_finish(self, context, instance_uuid,
                                floating_addresses, host=None,
                                rxtx_factor=None, project_id=None,
                                source=None, dest=None):
        # We only care if floating_addresses are provided and we're
        # switching hosts
        if host and not dest:
            dest = host
        if not floating_addresses or (source and source == dest):
            return

        LOG.info(_LI("Finishing migration network for instance %s"),
                 instance_uuid)

        for address in floating_addresses:
            floating_ip = objects.FloatingIP.get_by_address(context, address)

            if self._is_stale_floating_ip_address(context, floating_ip):
                LOG.warning(_LW("Floating IP address |%(address)s| no longer "
                                "belongs to instance %(instance_uuid)s. "
                                "Will not setup it."),
                            {'address': address,
                             'instance_uuid': instance_uuid})
                continue

            floating_ip.host = dest
            floating_ip.save()

            interface = CONF.public_interface or floating_ip.interface
            fixed_ip = floating_ip.fixed_ip
            self.l3driver.add_floating_ip(floating_ip.address,
                                          fixed_ip.address,
                                          interface,
                                          fixed_ip.network)

    def _prepare_domain_entry(self, context, domainref):
        scope = domainref.scope
        if scope == 'private':
            this_domain = {'domain': domainref.domain,
                         'scope': scope,
                         'availability_zone': domainref.availability_zone}
        else:
            this_domain = {'domain': domainref.domain,
                         'scope': scope,
                         'project': domainref.project_id}
        return this_domain

    def get_dns_domains(self, context):
        domains = []

        domain_list = objects.DNSDomainList.get_all(context)
        floating_driver_domain_list = self.floating_dns_manager.get_domains()
        instance_driver_domain_list = self.instance_dns_manager.get_domains()

        for dns_domain in domain_list:
            if (dns_domain.domain in floating_driver_domain_list or
                    dns_domain.domain in instance_driver_domain_list):
                domain_entry = self._prepare_domain_entry(context, dns_domain)
                if domain_entry:
                    domains.append(domain_entry)
            else:
                LOG.warning(_LW('Database inconsistency: DNS domain |%s| is '
                                'registered in the Nova db but not visible to '
                                'either the floating or instance DNS driver. '
                                'It will be ignored.'), dns_domain.domain)

        return domains

    def add_dns_entry(self, context, address, name, dns_type, domain):
        self.floating_dns_manager.create_entry(name, address,
                                               dns_type, domain)

    def modify_dns_entry(self, context, address, name, domain):
        self.floating_dns_manager.modify_address(name, address,
                                                 domain)

    def delete_dns_entry(self, context, name, domain):
        self.floating_dns_manager.delete_entry(name, domain)

    def _delete_all_entries_for_ip(self, context, address):
        domain_list = self.get_dns_domains(context)
        for domain in domain_list:
            names = self.get_dns_entries_by_address(context,
                                                    address,
                                                    domain['domain'])
            for name in names:
                self.delete_dns_entry(context, name, domain['domain'])

    def get_dns_entries_by_address(self, context, address, domain):
        return self.floating_dns_manager.get_entries_by_address(address,
                                                                domain)

    def get_dns_entries_by_name(self, context, name, domain):
        return self.floating_dns_manager.get_entries_by_name(name,
                                                             domain)

    def create_private_dns_domain(self, context, domain, av_zone):
        objects.DNSDomain.register_for_zone(context, domain, av_zone)
        try:
            self.instance_dns_manager.create_domain(domain)
        except exception.FloatingIpDNSExists:
            LOG.warning(_LW('Domain |%(domain)s| already exists, '
                            'changing zone to |%(av_zone)s|.'),
                        {'domain': domain, 'av_zone': av_zone})

    def create_public_dns_domain(self, context, domain, project):
        objects.DNSDomain.register_for_project(context, domain, project)
        try:
            self.floating_dns_manager.create_domain(domain)
        except exception.FloatingIpDNSExists:
            LOG.warning(_LW('Domain |%(domain)s| already exists, '
                            'changing project to |%(project)s|.'),
                        {'domain': domain, 'project': project})

    def delete_dns_domain(self, context, domain):
        objects.DNSDomain.delete_by_domain(context, domain)
        self.floating_dns_manager.delete_domain(domain)


class LocalManager(base.Base, FloatingIP):
    def __init__(self):
        super(LocalManager, self).__init__()
        # NOTE(vish): setting the host to none ensures that the actual
        #             l3driver commands for l3 are done via rpc.
        self.host = None
        self.servicegroup_api = servicegroup.API()
        self.network_rpcapi = network_rpcapi.NetworkAPI()
        self.floating_dns_manager = importutils.import_object(
                CONF.floating_ip_dns_manager)
        self.instance_dns_manager = importutils.import_object(
                CONF.instance_dns_manager)
        self.notifier = rpc.get_notifier('network', CONF.host)
