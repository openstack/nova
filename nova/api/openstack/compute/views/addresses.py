# Copyright 2010-2011 OpenStack Foundation
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

import collections
import itertools

from nova.api.openstack import common


class ViewBuilder(common.ViewBuilder):
    """Models server addresses as a dictionary."""

    _collection_name = "addresses"

    def basic(self, ip, extend_address=False):
        """Return a dictionary describing an IP address."""
        address = {
            "version": ip["version"],
            "addr": ip["address"],
        }
        if extend_address:
            address.update({
                "OS-EXT-IPS:type": ip["type"],
                "OS-EXT-IPS-MAC:mac_addr": ip['mac_address'],
            })
        return address

    def show(self, network, label, extend_address=False):
        """Returns a dictionary describing a network."""
        all_ips = itertools.chain(network["ips"], network["floating_ips"])
        return {label: [self.basic(ip, extend_address) for ip in all_ips]}

    def index(self, networks, extend_address=False):
        """Return a dictionary describing a list of networks."""
        addresses = collections.OrderedDict()
        for label, network in networks.items():
            network_dict = self.show(network, label, extend_address)
            addresses[label] = network_dict[label]
        return dict(addresses=addresses)
