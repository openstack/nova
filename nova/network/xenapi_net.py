# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
Implements vlans, bridges, and iptables rules using linux utilities.
"""

import os

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.xenapi_conn import XenAPISession
from nova.virt.xenapi.network_utils import NetworkHelper

LOG = logging.getLogger("nova.xenapi_net")

FLAGS = flags.FLAGS


def ensure_vlan_bridge(vlan_num, bridge, net_attrs=None):
    """Create a vlan and bridge unless they already exist"""
    #open xenapi session
    LOG.debug("ENTERING ensure_vlan_bridge in xenapi net")
    url = FLAGS.xenapi_connection_url
    username = FLAGS.xenapi_connection_username
    password = FLAGS.xenapi_connection_password
    session = XenAPISession(url, username, password)
    #check whether bridge already exists
    #retrieve network whose name_label is "bridge"
    network_ref = NetworkHelper.find_network_with_name_label(session, bridge)
    if network_ref == None:
        #if bridge does not exists
        #1 - create network
        description = "network for nova bridge %s" % bridge
        network_rec = {
                       'name_label': bridge,
                       'name_description': description,
                       'other_config': {},
                       }
        network_ref = session.call_xenapi('network.create', network_rec)
        #2 - find PIF for VLAN
        expr = 'field "device" = "%s" and \
                field "VLAN" = "-1"' % FLAGS.vlan_interface
        pifs = session.call_xenapi('PIF.get_all_records_where', expr)
        pif_ref = None
        #multiple PIF are ok: we are dealing with a pool
        if len(pifs) == 0:
            raise Exception(
                  _('Found no PIF for device %s') % FLAGS.vlan_interface)
        #3 - create vlan for network
        for pif_ref in pifs.keys():
            session.call_xenapi('VLAN.create', pif_ref,
                                str(vlan_num), network_ref)
    else:
        #check VLAN tag is appropriate
        network_rec = session.call_xenapi('network.get_record', network_ref)
        #retrieve PIFs from network
        for pif_ref in network_rec['PIFs']:
            #retrieve VLAN from PIF
            pif_rec = session.call_xenapi('PIF.get_record', pif_ref)
            pif_vlan = int(pif_rec['VLAN'])
            #raise an exception if VLAN <> vlan_num
            if pif_vlan != vlan_num:
                raise Exception(_("PIF %(pif_rec['uuid'])s for network "
                                  "%(bridge)s has VLAN id %(pif_vlan)d. "
                                  "Expected %(vlan_num)d") % locals())
