# Copyright 2012 Nicira Networks, Inc
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

from oslo_log import log as logging

from nova.network import linux_net
from nova import utils

LOG = logging.getLogger(__name__)


class L3Driver(object):
    """Abstract class that defines a generic L3 API."""

    def __init__(self, l3_lib=None):
        raise NotImplementedError()

    def initialize(self, **kwargs):
        """Set up basic L3 networking functionality."""
        raise NotImplementedError()

    def initialize_network(self, cidr, is_external):
        """Enable rules for a specific network."""
        raise NotImplementedError()

    def initialize_gateway(self, network_ref):
        """Set up a gateway on this network."""
        raise NotImplementedError()

    def remove_gateway(self, network_ref):
        """Remove an existing gateway on this network."""
        raise NotImplementedError()

    def is_initialized(self):
        """:returns: True/False (whether the driver is initialized)."""
        raise NotImplementedError()

    def add_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                        network=None):
        """Add a floating IP bound to the fixed IP with an optional
           l3_interface_id.  Some drivers won't care about the
           l3_interface_id so just pass None in that case. Network
           is also an optional parameter.
        """
        raise NotImplementedError()

    def remove_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                           network=None):
        raise NotImplementedError()

    def add_vpn(self, public_ip, port, private_ip):
        raise NotImplementedError()

    def remove_vpn(self, public_ip, port, private_ip):
        raise NotImplementedError()

    def clean_conntrack(self, fixed_ip):
        raise NotImplementedError()

    def teardown(self):
        raise NotImplementedError()


class LinuxNetL3(L3Driver):
    """L3 driver that uses linux_net as the backend."""
    def __init__(self):
        self.initialized = False

    def initialize(self, **kwargs):
        if self.initialized:
            return
        LOG.debug("Initializing linux_net L3 driver")
        fixed_range = kwargs.get('fixed_range', False)
        networks = kwargs.get('networks', None)
        if not fixed_range and networks is not None:
            for network in networks:
                if network['enable_dhcp']:
                    is_ext = (network['dhcp_server'] is not None and
                              network['dhcp_server'] != network['gateway'])
                    self.initialize_network(network['cidr'], is_ext)
        linux_net.ensure_metadata_ip()
        linux_net.metadata_forward()
        self.initialized = True

    def is_initialized(self):
        return self.initialized

    def initialize_network(self, cidr, is_external):
        linux_net.init_host(cidr, is_external)

    def initialize_gateway(self, network_ref):
        mac_address = utils.generate_mac_address()
        dev = linux_net.plug(network_ref, mac_address,
                    gateway=(network_ref['gateway'] is not None))
        linux_net.initialize_gateway_device(dev, network_ref)

    def remove_gateway(self, network_ref):
        linux_net.unplug(network_ref)

    def add_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                        network=None):
        linux_net.ensure_floating_forward(floating_ip, fixed_ip,
                                          l3_interface_id, network)
        linux_net.bind_floating_ip(floating_ip, l3_interface_id)

    def remove_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                           network=None):
        linux_net.unbind_floating_ip(floating_ip, l3_interface_id)
        linux_net.remove_floating_forward(floating_ip, fixed_ip,
                                          l3_interface_id, network)
        linux_net.clean_conntrack(fixed_ip)

    def add_vpn(self, public_ip, port, private_ip):
        linux_net.ensure_vpn_forward(public_ip, port, private_ip)

    def remove_vpn(self, public_ip, port, private_ip):
        # Linux net currently doesn't implement any way of removing
        # the VPN forwarding rules
        pass

    def teardown(self):
        pass


class NullL3(L3Driver):
    """The L3 driver that doesn't do anything.  This class can be used when
       nova-network should not manipulate L3 forwarding at all (e.g., in a Flat
       or FlatDHCP scenario).
    """
    def __init__(self):
        pass

    def initialize(self, **kwargs):
        pass

    def is_initialized(self):
        return True

    def initialize_network(self, cidr, is_external):
        pass

    def initialize_gateway(self, network_ref):
        pass

    def remove_gateway(self, network_ref):
        pass

    def add_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                        network=None):
        pass

    def remove_floating_ip(self, floating_ip, fixed_ip, l3_interface_id,
                           network=None):
        pass

    def add_vpn(self, public_ip, port, private_ip):
        pass

    def remove_vpn(self, public_ip, port, private_ip):
        pass

    def clean_conntrack(self, fixed_ip):
        pass

    def teardown(self):
        pass
