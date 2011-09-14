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

"""VIF drivers for VMWare."""

from nova import exception
from nova import flags
from nova import log as logging
from nova.virt.vif import VIFDriver
from nova.virt.vmwareapi import network_utils


LOG = logging.getLogger("nova.virt.vmwareapi.vif")

FLAGS = flags.FLAGS
FLAGS['vmwareapi_vlan_interface'].SetDefault('vmnic0')


class VMWareVlanBridgeDriver(VIFDriver):
    """VIF Driver to setup bridge/VLAN networking using VMWare API."""

    def plug(self, instance, network, mapping):
        """Plug the VIF to specified instance using information passed.
        Currently we are plugging the VIF(s) during instance creation itself.
        We can use this method when we add support to add additional NIC to
        an existing instance."""
        pass

    def ensure_vlan_bridge(self, session, network):
        """Create a vlan and bridge unless they already exist."""
        vlan_num = network['vlan']
        bridge = network['bridge']
        vlan_interface = FLAGS.vmwareapi_vlan_interface

        # Check if the vlan_interface physical network adapter exists on the
        # host.
        if not network_utils.check_if_vlan_interface_exists(session,
                                                            vlan_interface):
            raise exception.NetworkAdapterNotFound(adapter=vlan_interface)

        # Get the vSwitch associated with the Physical Adapter
        vswitch_associated = network_utils.get_vswitch_for_vlan_interface(
                                            session, vlan_interface)
        if vswitch_associated is None:
            raise exception.SwitchNotFoundForNetworkAdapter(
                adapter=vlan_interface)
        # Check whether bridge already exists and retrieve the the ref of the
        # network whose name_label is "bridge"
        network_ref = network_utils.get_network_with_the_name(session, bridge)
        if network_ref is None:
            # Create a port group on the vSwitch associated with the
            # vlan_interface corresponding physical network adapter on the ESX
            # host.
            network_utils.create_port_group(session, bridge,
                                            vswitch_associated, vlan_num)
        else:
            # Get the vlan id and vswitch corresponding to the port group
            pg_vlanid, pg_vswitch = \
                network_utils.get_vlanid_and_vswitch_for_portgroup(session,
                                                                   bridge)

            # Check if the vswitch associated is proper
            if pg_vswitch != vswitch_associated:
                raise exception.InvalidVLANPortGroup(
                    bridge=bridge, expected=vswitch_associated,
                    actual=pg_vswitch)

            # Check if the vlan id is proper for the port group
            if pg_vlanid != vlan_num:
                raise exception.InvalidVLANTag(bridge=bridge, tag=vlan_num,
                                               pgroup=pg_vlanid)

    def unplug(self, instance, network, mapping):
        """Cleanup operations like deleting port group if no instance
        is associated with it."""
        pass
