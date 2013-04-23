# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

"""VIF drivers for VMware."""

from oslo.config import cfg

from nova import exception
from nova.virt.vmwareapi import network_util


CONF = cfg.CONF

vmwareapi_vif_opts = [
    cfg.StrOpt('vmwareapi_vlan_interface',
               default='vmnic0',
               help='Physical ethernet adapter name for vlan networking'),
]

CONF.register_opts(vmwareapi_vif_opts)


def ensure_vlan_bridge(session, vif, cluster=None, create_vlan=True):
    """Create a vlan and bridge unless they already exist."""
    vlan_num = vif['network'].get_meta('vlan')
    bridge = vif['network']['bridge']
    vlan_interface = CONF.vmwareapi_vlan_interface

    network_ref = network_util.get_network_with_the_name(session, bridge,
                                                         cluster)
    # Get the vSwitch associated with the Physical Adapter
    vswitch_associated = network_util.get_vswitch_for_vlan_interface(
                                    session, vlan_interface, cluster)
    if vswitch_associated is None:
        raise exception.SwitchNotFoundForNetworkAdapter(
            adapter=vlan_interface)
    # Check if the vlan_interface physical network adapter exists on the
    # host.
    if not network_util.check_if_vlan_interface_exists(session,
                                        vlan_interface, cluster):
        raise exception.NetworkAdapterNotFound(adapter=vlan_interface)
    if create_vlan:

        if network_ref is None:
        # Create a port group on the vSwitch associated with the
        # vlan_interface corresponding physical network adapter on the ESX
        # host.
            network_util.create_port_group(session, bridge,
                                       vswitch_associated, vlan_num,
                                       cluster)
        else:
            # Get the vlan id and vswitch corresponding to the port group
            _get_pg_info = network_util.get_vlanid_and_vswitch_for_portgroup
            pg_vlanid, pg_vswitch = _get_pg_info(session, bridge, cluster)

            # Check if the vswitch associated is proper
            if pg_vswitch != vswitch_associated:
                raise exception.InvalidVLANPortGroup(
                    bridge=bridge, expected=vswitch_associated,
                    actual=pg_vswitch)

            # Check if the vlan id is proper for the port group
            if pg_vlanid != vlan_num:
                raise exception.InvalidVLANTag(bridge=bridge, tag=vlan_num,
                                           pgroup=pg_vlanid)
    else:
        if network_ref is None:
            network_util.create_port_group(session, bridge,
                                       vswitch_associated, 0,
                                       cluster)
