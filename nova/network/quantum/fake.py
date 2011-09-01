# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Nicira Networks, Inc
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

from nova import exception
from nova import ipv6
from nova import log as logging
from nova import utils


LOG = logging.getLogger("network.quantum.fake")


# this class can be used for unit functional/testing on nova,
# as it does not actually make remote calls to the Quantum service
class FakeQuantumClientConnection(object):

    def __init__(self):
        self.nets = {}

    def get_networks_for_tenant(self, tenant_id):
        net_ids = []
        for net_id, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                net_ids.append(net_id)
        return net_ids

    def create_network(self, tenant_id, network_name):

        uuid = str(utils.gen_uuid())
        self.nets[uuid] = {'net-name': network_name,
                           'tenant-id': tenant_id,
                           'ports': {}}
        return uuid

    def delete_network(self, tenant_id, net_id):
        if self.nets[net_id]['tenant-id'] == tenant_id:
            del self.nets[net_id]

    def network_exists(self, tenant_id, net_id):
        try:
            return self.nets[net_id]['tenant-id'] == tenant_id
        except KeyError:
            return False

    def _confirm_not_attached(self, interface_id):
        for n in self.nets.values():
            for p in n['ports'].values():
                if p['attachment-id'] == interface_id:
                    raise Exception(_("interface '%s' is already attached" %
                                          interface_id))

    def create_and_attach_port(self, tenant_id, net_id, interface_id):
        if not self.network_exists(tenant_id, net_id):
            raise Exception(
                _("network %(net_id)s does not exist for tenant %(tenant_id)"
                    % locals()))

        self._confirm_not_attached(interface_id)
        uuid = str(utils.gen_uuid())
        self.nets[net_id]['ports'][uuid] = \
                {"port-state": "ACTIVE",
                "attachment-id": interface_id}

    def detach_and_delete_port(self, tenant_id, net_id, port_id):
        if not self.network_exists(tenant_id, net_id):
            raise exception.NotFound(
                    _("network %(net_id)s does not exist "
                        "for tenant %(tenant_id)s" % locals()))
        del self.nets[net_id]['ports'][port_id]

    def get_port_by_attachment(self, tenant_id, attachment_id):
        for net_id, n in self.nets.items():
            if n['tenant-id'] == tenant_id:
                for port_id, p in n['ports'].items():
                    if p['attachment-id'] == attachment_id:
                        return (net_id, port_id)

        return (None, None)
