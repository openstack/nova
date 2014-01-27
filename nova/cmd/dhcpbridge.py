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

from oslo.config import cfg

from nova import config
from nova import context
from nova import db
from nova.network import rpcapi as network_rpcapi
from nova.openstack.common.gettextutils import _
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova import rpc

CONF = cfg.CONF
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('network_manager', 'nova.service')
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
                         CONF.host)


def init_leases(network_id):
    """Get the list of hosts for a network."""
    ctxt = context.get_admin_context()
    network_ref = db.network_get(ctxt, network_id)
    network_manager = importutils.import_object(CONF.network_manager)
    return network_manager.get_dhcp_leases(ctxt, network_ref)


def add_action_parsers(subparsers):
    parser = subparsers.add_parser('init')

    # NOTE(cfb): dnsmasq always passes mac, and ip. hostname
    #            is passed if known. We don't care about
    #            hostname, but argparse will complain if we
    #            do not accept it.
    for action in ['add', 'del', 'old']:
        parser = subparsers.add_parser(action)
        parser.add_argument('mac')
        parser.add_argument('ip')
        parser.add_argument('hostname', nargs='?', default='')
        parser.set_defaults(func=globals()[action + '_lease'])


CONF.register_cli_opt(
    cfg.SubCommandOpt('action',
                      title='Action options',
                      help='Available dhcpbridge options',
                      handler=add_action_parsers))


def main():
    """Parse environment and arguments and call the appropriate action."""
    config.parse_args(sys.argv,
        default_config_files=jsonutils.loads(os.environ['CONFIG_FILE']))

    logging.setup("nova")
    global LOG
    LOG = logging.getLogger('nova.dhcpbridge')

    if CONF.action.name in ['add', 'del', 'old']:
        msg = (_("Called '%(action)s' for mac '%(mac)s' with ip '%(ip)s'") %
               {"action": CONF.action.name,
                "mac": CONF.action.mac,
                "ip": CONF.action.ip})
        LOG.debug(msg)
        CONF.action.func(CONF.action.mac, CONF.action.ip)
    else:
        try:
            network_id = int(os.environ.get('NETWORK_ID'))
        except TypeError:
            LOG.error(_("Environment variable 'NETWORK_ID' must be set."))
            return(1)

        print(init_leases(network_id))

    rpc.cleanup()
