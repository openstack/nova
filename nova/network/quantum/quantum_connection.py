# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Nicira Networks
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
from nova import log as logging
from nova.network.quantum import client as quantum_client
from nova import utils


LOG = logging.getLogger("nova.network.quantum")
FLAGS = flags.FLAGS

flags.DEFINE_string('quantum_connection_host',
                    '127.0.0.1',
                    'HOST for connecting to quantum')

flags.DEFINE_string('quantum_connection_port',
                    '9696',
                    'PORT for connecting to quantum')

flags.DEFINE_string('quantum_default_tenant_id',
                    "default",
                    'Default tenant id when creating quantum networks')


class QuantumClientConnection:

    def __init__(self):
        self.client = quantum_client.Client(FLAGS.quantum_connection_host,
                                            FLAGS.quantum_connection_port,
                                            format="json",
                                            logger=LOG)

    def create_network(self, tenant_id, network_name):
        data = {'network': {'name': network_name}}
        resdict = self.client.create_network(data, tenant=tenant_id)
        return resdict["network"]["id"]

    def delete_network(self, tenant_id, net_id):
        self.client.delete_network(net_id, tenant=tenant_id)

    def network_exists(self, tenant_id, net_id):
        try:
            self.client.show_network_details(net_id, tenant=tenant_id)
        except:
            # FIXME: client lib should expose more granular exceptions
            # so we can confirm we're getting a 404 and not some other error
            return False
        return True

    def create_and_attach_port(self, tenant_id, net_id, interface_id):
        LOG.debug("Connecting interface %s to net %s for %s" % \
                    (interface_id, net_id, tenant_id))
        port_data = {'port': {'port-state': 'ACTIVE'}}
        resdict = self.client.create_port(net_id, port_data, tenant=tenant_id)
        port_id = resdict["ports"]["port"]["id"]

        attach_data = {'port': {'attachment-id': interface_id}}
        self.client.attach_resource(net_id, port_id, attach_data,
                                    tenant=tenant_id)

    def detach_and_delete_port(self, tenant_id, net_id, port_id):
        LOG.debug("Deleteing port %s on net %s for %s" % \
                    (port_id, net_id, tenant_id))

        self.client.detach_resource(net_id, port_id, tenant=tenant_id)
        self.client.delete_port(net_id, port_id, tenant=tenant_id)

    # FIXME: this will be inefficient until API implements querying
    def get_port_by_attachment(self, tenant_id, attachment_id):

        net_list_resdict = self.client.list_networks(tenant=tenant_id)
        for n in net_list_resdict["networks"]:
            net_id = n['id']
            port_list_resdict = self.client.list_ports(net_id,
                                            tenant=tenant_id)
            for p in port_list_resdict["ports"]:
                port_id = p["id"]
                port_get_resdict = self.client.show_port_attachment(net_id,
                                port_id, tenant=tenant_id)
                if attachment_id == port_get_resdict["attachment"]:
                    return (net_id, port_id)
        return (None, None)
