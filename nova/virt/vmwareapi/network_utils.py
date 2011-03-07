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
Utility functions for ESX Networking
"""

from nova import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util
from nova.virt.vmwareapi.vim import VimException

LOG = logging.getLogger("nova.virt.vmwareapi.network_utils")

PORT_GROUP_EXISTS_EXCEPTION = \
        'The specified key, name, or identifier already exists.'


class NetworkHelper:

    @classmethod
    def get_network_with_the_name(cls, session, network_name="vmnet0"):
        """ Gets reference to the network whose name is passed as the
        argument. """
        datacenters = session._call_method(vim_util, "get_objects",
                    "Datacenter", ["network"])
        vm_networks = datacenters[0].propSet[0].val.ManagedObjectReference
        networks = session._call_method(vim_util,
                           "get_properites_for_a_collection_of_objects",
                           "Network", vm_networks, ["summary.name"])
        for network in networks:
            if network.propSet[0].val == network_name:
                return network.obj
        return None

    @classmethod
    def get_vswitch_for_vlan_interface(cls, session, vlan_interface):
        """ Gets the vswitch associated with the physical
        network adapter with the name supplied"""
        #Get the list of vSwicthes on the Host System
        host_mor = session._call_method(vim_util, "get_objects",
             "HostSystem")[0].obj
        vswitches = session._call_method(vim_util,
                    "get_dynamic_property", host_mor,
                    "HostSystem", "config.network.vswitch").HostVirtualSwitch
        #Get the vSwitch associated with the network adapter
        for elem in vswitches:
            try:
                for nic_elem in elem.pnic:
                    if str(nic_elem).split('-')[-1].find(vlan_interface) != -1:
                        return elem.name
            except Exception:
                pass

    @classmethod
    def check_if_vlan_interface_exists(cls, session, vlan_interface):
        """ Checks if the vlan_inteface exists on the esx host """
        host_net_system_mor = session._call_method(vim_util, "get_objects",
             "HostSystem", ["configManager.networkSystem"])[0].propSet[0].val
        physical_nics = session._call_method(vim_util,
                    "get_dynamic_property", host_net_system_mor,
                    "HostNetworkSystem", "networkInfo.pnic").PhysicalNic
        for pnic in physical_nics:
            if vlan_interface == pnic.device:
                return True
        return False

    @classmethod
    def get_vlanid_and_vswicth_for_portgroup(cls, session, pg_name):
        """ Get the vlan id and vswicth associated with the port group """
        host_mor = session._call_method(vim_util, "get_objects",
             "HostSystem")[0].obj
        port_grps_on_host = session._call_method(vim_util,
                    "get_dynamic_property", host_mor,
                    "HostSystem", "config.network.portgroup").HostPortGroup
        for p_gp in port_grps_on_host:
            if p_gp.spec.name == pg_name:
                p_grp_vswitch_name = p_gp.vswitch.split("-")[-1]
                return p_gp.spec.vlanId, p_grp_vswitch_name

    @classmethod
    def create_port_group(cls, session, pg_name, vswitch_name, vlan_id=0):
        """ Creates a port group on the host system with the vlan tags
        supplied. VLAN id 0 means no vlan id association """
        client_factory = session._get_vim().client.factory
        add_prt_grp_spec = vm_util.get_add_vswitch_port_group_spec(
                        client_factory,
                        vswitch_name,
                        pg_name,
                        vlan_id)
        host_mor = session._call_method(vim_util, "get_objects",
             "HostSystem")[0].obj
        network_system_mor = session._call_method(vim_util,
            "get_dynamic_property", host_mor,
            "HostSystem", "configManager.networkSystem")
        LOG.debug(_("Creating Port Group with name %s on "
                    "the ESX host") % pg_name)
        try:
            session._call_method(session._get_vim(),
                    "AddPortGroup", network_system_mor,
                    portgrp=add_prt_grp_spec)
        except VimException, exc:
            #There can be a race condition when two instances try
            #adding port groups at the same time. One succeeds, then
            #the other one will get an exception. Since we are
            #concerned with the port group being created, which is done
            #by the other call, we can ignore the exception.
            if str(exc).find(PORT_GROUP_EXISTS_EXCEPTION) == -1:
                raise Exception(exc)
        LOG.debug(_("Created Port Group with name %s on "
                    "the ESX host") % pg_name)
