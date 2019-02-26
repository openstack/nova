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

"""Utility methods for linux networking."""

from oslo_log import log as logging

from nova.pci import utils as pci_utils
import nova.privsep.linux_net


LOG = logging.getLogger(__name__)


def set_vf_interface_vlan(pci_addr, mac_addr, vlan=0):
    pf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr,
                                                    pf_interface=True)
    vf_ifname = pci_utils.get_ifname_by_pci_address(pci_addr)
    vf_num = pci_utils.get_vf_num_by_pci_address(pci_addr)

    nova.privsep.linux_net.set_device_macaddr_and_vlan(
        pf_ifname, vf_num, mac_addr, vlan)

    # Bring up/down the VF's interface
    # TODO(edand): The mac is assigned as a workaround for the following issue
    #              https://bugzilla.redhat.com/show_bug.cgi?id=1372944
    #              once resolved it will be removed
    port_state = 'up' if vlan > 0 else 'down'
    nova.privsep.linux_net.set_device_macaddr(vf_ifname, mac_addr,
                                              port_state=port_state)
