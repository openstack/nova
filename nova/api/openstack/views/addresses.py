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

import itertools

from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.api.openstack.views.addresses')


class ViewBuilder(object):
    """Models a server addresses response as a python dictionary."""

    def build(self, inst):
        raise NotImplementedError()

    def _extract_ips(self, network, key=None):
        if key:
            chain = network[key]
        else:
            chain = itertools.chain(network['ips'], network['floating_ips'])
        for ip in chain:
            if not FLAGS.use_ipv6 and ip['version'] == 6:
                continue
            yield ip


class ViewBuilderV10(ViewBuilder):

    def build(self, networks):
        if not networks:
            return dict(public=[], private=[])

        return dict(public=self.build_public_parts(networks),
                    private=self.build_private_parts(networks))

    def build_public_parts(self, nets):
        ips = [self._extract_ips(nets[label],
                                 key='floating_ips') for label in nets]
        return [ip['addr'] for ip in itertools.chain(*ips)]

    def build_private_parts(self, nets):
        ips = [self._extract_ips(nets[label], key='ips') for label in nets]
        return [ip['addr'] for ip in itertools.chain(*ips)]


class ViewBuilderV11(ViewBuilder):

    def build(self, networks):
        result = {}
        for network in networks:
            if network not in result:
                result[network] = []

            result[network].extend(self._extract_ips(networks[network]))
        return result

    def build_network(self, networks, requested_network):
        for network in networks:
            if network == requested_network:
                return {network: list(self._extract_ips(networks[network]))}
        return None

    def _extract_network_label(self, network):
        try:
            return network['label']
        except (TypeError, KeyError) as exc:
            raise TypeError
