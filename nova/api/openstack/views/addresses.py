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

from nova import flags
from nova import utils
from nova import log as logging
from nova.api.openstack import common

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack.views.addresses')


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
            try:
                network_label = self._extract_network_label(interface)
            except TypeError:
                continue

            if network_label not in networks:
                networks[network_label] = []

            ip_addresses = list(self._extract_ipv4_addresses(interface))

            if FLAGS.use_ipv6:
                ipv6_address = self._extract_ipv6_address(interface)
                if ipv6_address is not None:
                    ip_addresses.append(ipv6_address)

            networks[network_label].extend(ip_addresses)

        return networks

    def build_network(self, interfaces, requested_network):
        for interface in interfaces:
            try:
                network_label = self._extract_network_label(interface)
            except TypeError:
                continue

            if network_label == requested_network:
                ips = list(self._extract_ipv4_addresses(interface))
                ipv6 = self._extract_ipv6_address(interface)
                if ipv6 is not None:
                    ips.append(ipv6)
                return {network_label: ips}
        return None

    def _extract_network_label(self, interface):
        try:
            return interface['network']['label']
        except (TypeError, KeyError) as exc:
            raise TypeError

    def _extract_ipv4_addresses(self, interface):
        for fixed_ip in interface['fixed_ips']:
            yield self._build_ip_entity(fixed_ip['address'], 4)
            for floating_ip in fixed_ip.get('floating_ips', []):
                yield self._build_ip_entity(floating_ip['address'], 4)

    def _extract_ipv6_address(self, interface):
        fixed_ipv6 = interface.get('fixed_ipv6')
        if fixed_ipv6 is not None:
            return self._build_ip_entity(fixed_ipv6, 6)

    def _build_ip_entity(self, address, version):
        return {'addr': address, 'version': version}
