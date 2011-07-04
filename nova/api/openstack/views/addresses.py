# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

from nova import utils
from nova.api.openstack import common


class ViewBuilder(object):
    """Models a server addresses response as a python dictionary."""

    def build(self, inst):
        raise NotImplementedError()


class ViewBuilderV10(ViewBuilder):

    def build(self, inst):
        private_ips = self.build_private_parts(inst)
        public_ips = self.build_public_parts(inst)
        return dict(public=public_ips, private=private_ips)

    def build_public_parts(self, inst):
        return utils.get_from_path(inst, 'fixed_ips/floating_ips/address')

    def build_private_parts(self, inst):
        return utils.get_from_path(inst, 'fixed_ips/address')


class ViewBuilderV11(ViewBuilder):

    def build(self, interfaces):
        networks = {}
        for interface in interfaces:
            network_label = interface['network']['label']
            if network_label not in networks:
                networks[network_label] = []

            for fixed_ip in interface['fixed_ips']:
                ip = {'addr': fixed_ip['address'], 'version': 4}
                networks[network_label].append(ip)
        return networks

    def build_network(self, interfaces, network_label):
        for interface in interfaces:
            if interface['network']['label'] == network_label:
                ips = self._extract_fixed_ips(interface)
                return {network_label: ips}
        return None

    def _extract_fixed_ips(self, interface):
        fixed_ips = []
        for fixed_ip in interface['fixed_ips']:
            ip = {'addr': fixed_ip['address'], 'version': 4}
            fixed_ips.append(ip)
        return fixed_ips

