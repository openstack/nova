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

"""
Handle lease database updates from DHCP servers.
"""

from __future__ import print_function

import os
import sys

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils

from nova.cmd import common as cmd_common
from nova.conductor import rpcapi as conductor_rpcapi
import nova.conf
from nova import config
from nova import context
from nova.network import rpcapi as network_rpcapi
from nova import objects
from nova.objects import base as objects_base
from nova import rpc

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def add_lease(mac, ip_address):
    """Set the IP that was assigned by the DHCP server."""
    api = network_rpcapi.NetworkAPI()
    api.lease_fixed_ip(context.get_admin_context(), ip_address, CONF.host)


def old_lease(mac, ip_address):
    """Called when an old lease is recognized."""
    # NOTE(vish): We assume we heard about this lease the first time.
    #             If not, we will get it the next time the lease is
    #             renewed.
    pass


def del_lease(mac, ip_address):
    """Called when a lease expires."""
    api = network_rpcapi.NetworkAPI()
    api.release_fixed_ip(context.get_admin_context(), ip_address,
                         CONF.host, mac)


def init_leases(network_id):
    """Get the list of hosts for a network."""
    ctxt = context.get_admin_context()
    network = objects.Network.get_by_id(ctxt, network_id)
    network_manager = importutils.import_object(CONF.network_manager)
    return network_manager.get_dhcp_leases(ctxt, network)


def add_action_parsers(subparsers):
    subparsers.add_parser('init')

    # NOTE(cfb): dnsmasq always passes mac, and ip. hostname
    #            is passed if known. We don't care about
    #            hostname, but argparse will complain if we
    #            do not accept it.
    actions = {
        'add': add_lease,
        'del': del_lease,
        'old': old_lease,
    }
    for action, func in actions.items():
        parser = subparsers.add_parser(action)
        parser.add_argument('mac')
        parser.add_argument('ip')
        parser.add_argument('hostname', nargs='?', default='')
        parser.set_defaults(func=func)


CONF.register_cli_opt(
    cfg.SubCommandOpt('action',
                      title='Action options',
                      help='Available dhcpbridge options',
                      handler=add_action_parsers))


def main():
    """Parse environment and arguments and call the appropriate action."""
    config.parse_args(sys.argv,
        default_config_files=jsonutils.loads(os.environ['CONFIG_FILE']))

    logging.setup(CONF, "nova")
    global LOG
    LOG = logging.getLogger('nova.dhcpbridge')

    if CONF.action.name == 'old':
        # NOTE(sdague): old is the most frequent message sent, and
        # it's a noop. We should just exit immediately otherwise we
        # can stack up a bunch of requests in dnsmasq. A SIGHUP seems
        # to dump this list, so actions queued up get lost.
        return

    objects.register_all()

    cmd_common.block_db_access('nova-dhcpbridge')
    objects_base.NovaObject.indirection_api = conductor_rpcapi.ConductorAPI()

    if CONF.action.name in ['add', 'del']:
        LOG.debug("Called '%(action)s' for mac '%(mac)s' with IP '%(ip)s'",
                  {"action": CONF.action.name,
                   "mac": CONF.action.mac,
                   "ip": CONF.action.ip})
        CONF.action.func(CONF.action.mac, CONF.action.ip)
    else:
        try:
            network_id = int(os.environ.get('NETWORK_ID'))
        except TypeError:
            LOG.error("Environment variable 'NETWORK_ID' must be set.")
            return 1

        print(init_leases(network_id))

    rpc.cleanup()
