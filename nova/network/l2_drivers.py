# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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

"""Drivers responsible for managing L2 connectivity for Nova."""

from nova.network import linux_net

class L2Driver(object):
    """Base class that defines interfaces for L2 drivers."""

    def ensure_bridge(self, bridge, interface, net_attrs=None):
        """Create a bridge unless it already exists."""
        raise NotImplementedError()

    def ensure_vlan(self, vlan_num, bridge_interface, net_attrs=None):
        """Create a vlan unless it already exists."""
        raise NotImplementedError()


class LinuxBridgeDriver(L2Driver):
    """L2 driver based on Linux Bridge."""
    
    def ensure_bridge(self, bridge, interface, net_attrs=None):
        """Create a Linux bridge unless it already eixsts."""
        linux_net.ensure_bridge(bridge, interface, net_attrs)

    def ensure_vlan(self, vlan_num, bridge_interface, net_attrs=None):
        """Create a vlan unless it already exists."""
        return linux_net.ensure_vlan(vlan_num, bridge_interface, net_attrs)


class QuantumDriver(L2Driver):
    """L2 driver based on Quantum network service."""

    def ensure_bridge(self, bridge, interface, net_attrs=None):
        """Do nothing."""
        pass

    def ensure_vlan(self, vlan_num, bridge_interface, net_attrs=None):
        """Return None."""
        return None
    
