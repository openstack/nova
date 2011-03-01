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
Implements vlans for vmwareapi
"""

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.virt.vmwareapi_conn import VMWareAPISession
from nova.virt.vmwareapi.network_utils import NetworkHelper

LOG = logging.getLogger("nova.vmwareapi_net")

FLAGS = flags.FLAGS
flags.DEFINE_string('vlan_interface', 'vmnic0',
                    'Physical network adapter name in VMware ESX host for '
                    'vlan networking')


def metadata_forward():
    pass


def init_host():
    pass


def bind_floating_ip(floating_ip, check_exit_code=True):
    pass


def unbind_floating_ip(floating_ip):
    pass


def ensure_vlan_forward(public_ip, port, private_ip):
    pass


def ensure_floating_forward(floating_ip, fixed_ip):
    pass


def remove_floating_forward(floating_ip, fixed_ip):
    pass


def ensure_vlan_bridge(vlan_num, bridge, net_attrs=None):
    """Create a vlan and bridge unless they already exist"""
    #open vmwareapi session
    host_ip = FLAGS.vmwareapi_host_ip
    host_username = FLAGS.vmwareapi_host_username
    host_password = FLAGS.vmwareapi_host_password
    if not host_ip or host_username is None or host_password is None:
        raise Exception(_("Must specify vmwareapi_host_ip,"
                        "vmwareapi_host_username "
                        "and vmwareapi_host_password to use"
                        "connection_type=vmwareapi"))
    session = VMWareAPISession(host_ip, host_username, host_password,
                               FLAGS.vmwareapi_api_retry_count)
    vlan_interface = FLAGS.vlan_interface
    #check whether bridge already exists
    #retrieve network whose name_label is "bridge"
    network_ref = NetworkHelper.get_network_with_the_name(session, bridge)
    if network_ref == None:
        #Create a port group on the vSwitch associated with the vlan_interface
        #corresponding physical network adapter on the ESX host
        vswitches = NetworkHelper.get_vswitches_for_vlan_interface(session,
                                           vlan_interface)
        if len(vswitches) == 0:
            raise Exception(_("There is no virtual switch connected "
                "to the physical network adapter with name %s") %
                vlan_interface)
        #Assuming physical network interface is associated with only one
        #virtual switch
        NetworkHelper.create_port_group(session, bridge, vswitches[0],
                                        vlan_num)
    else:
        #check VLAN tag is appropriate
        is_vlan_proper, ret_vlan_id = NetworkHelper.check_if_vlan_id_is_proper(
                                           session, bridge, vlan_num)
        if not is_vlan_proper:
            raise Exception(_("VLAN tag not appropriate for the port group "
                              "%(bridge)s. Expected VLAN tag is %(vlan_num)s, "
                              "but the one associated with the port group is"
                              " %(ret_vlan_id)s") % locals())


def ensure_vlan(vlan_num):
    pass


def ensure_bridge(bridge, interface, net_attrs=None):
    pass


def get_dhcp_hosts(context, network_id):
    pass


def update_dhcp(context, network_id):
    pass


def update_ra(context, network_id):
    pass
