# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Nicira Networks
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
#    @author: Dan Wendlandt Nicira Networks

import copy

from nova import utils
from nova.network.quantum import client

#TODO(danwent): would be nice to have these functions raise QuantumIOErrors
# to make sure such errors are caught and reported properly


#  this is a fake quantum client that just stores all data in a nested dict
#
#  example:
#
#{'<tenant>':
# { '<net-uuid>' : { 'name' : "t1-net1",
#                    'ports' : [ { '<port-uuid'> :
#                                        {'state': 'Active',
#                                       'attachment': 'iface-id'},
#                                       { 'state': 'Down',
#                                         'attachment' : None}}]
#                      }
#   }
#  }


class FakeClient(object):
    """A fake Quantum Client for testing"""

    def __init__(self, logger=None, **kwargs):
        """Creates a new client to some service.
        :param logger: logging object to be used by client library
        """
        self.logger = logger
        self.tenant_map = {}

    def _get_tenant_nets(self, tenant):
        if tenant is None:
            raise Exception("'tenant' cannot be None")
        return self.tenant_map.setdefault(tenant, {})

    def _verify_net(self, network, nets):
        if network not in nets:
            raise client.QuantumNotFoundException("no network with uuid %s"
                                                                % network)

    def _verify_net_and_port(self, network, port, nets):
        if network not in nets:
            raise client.QuantumNotFoundException("no network with uuid %s"
                                                                % network)
        if port not in nets[network]['ports']:
            raise client.QuantumNotFoundException("no port with uuid %s"
                                                                   % port)

    def list_networks(self, tenant=None, filter_ops=None):
        """Fetches a list of all networks for a tenant"""
        nets = self._get_tenant_nets(tenant)
        if filter_ops:
            raise Exception("Need to implement filters %s in "
                        "quantum fake client" % filter_ops)
        return {"networks": [{"id": uuid} for uuid in nets.keys()]}

    def show_network_details(self, network, tenant=None):
        """Fetches the details of a certain network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net(network, nets)
        return {"network": {"id": network, "name": nets[network]["name"]}}

    def create_network(self, body=None, tenant=None):
        """Creates a new network"""
        nets = self._get_tenant_nets(tenant)
        uuid = str(utils.gen_uuid())
        name = body["network"]["name"]
        nets[uuid] = {"ports": {}, "name": name}
        return {"network": {"id": uuid}}

    def update_network(self, network, body=None, tenant=None):
        """Updates a network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net(network, nets)
        nets[network]['name'] = body["network"]["name"]
        return {"network": {"id": network, "name": nets[networks]["name"]}}

    def delete_network(self, network, tenant=None):
        """Deletes the specified network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net(network, nets)
        del nets[network]

    def list_ports(self, network, filter_ops=None, tenant=None):
        """Fetches a list of ports on a given network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net(network, nets)

        ports = nets[network]['ports'].items()
        if filter_ops and 'attachment' in filter_ops:
            a = filter_ops.pop('attachment')
            ports = [p for p in ports if p[1]['attachment'] == a]

        if filter_ops:
            raise Exception("Need to implement files %s in "
                        "quantum fake client" % filter_ops)

        return {"ports": [{'id': p[0]} for p in ports]}

    def show_port_details(self, network, port, tenant=None):
        """Fetches the details of a certain port"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)
        p = nets[network]['ports'][port]
        return {"port": {"state": p["state"], "id": port}}

    def create_port(self, network, body=None, tenant=None):
        """Creates a new port on a given network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net(network, nets)
        uuid = str(utils.gen_uuid())
        nets[network]['ports'][uuid] = {'attachment': None,
                                        'state': body['port']['state']}
        return {"port": {"id": uuid}}

    def delete_port(self, network, port, tenant=None):
        """Deletes the specified port from a network"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)
        del nets[network]['ports'][port]

    def set_port_state(self, network, port, body=None, tenant=None):
        """Sets the state of the specified port"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)

        new_state = body['port']['state']
        nets[network]['ports'][port]['state'] = new_state
        return {"port": {"state": new_state}}

    def show_port_attachment(self, network, port, tenant=None):
        """Fetches the attachment-id associated with the specified port"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)
        p = nets[network]['ports'][port]
        if p['attachment'] is not None:
            return {"attachment": {"id": p['attachment']}}
        else:
            return {"attachment": {}}

    def attach_resource(self, network, port, body=None, tenant=None):
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)
        nets[network]['ports'][port]['attachment'] = body['attachment']['id']

    def detach_resource(self, network, port, tenant=None):
        """Removes the attachment-id of the specified port"""
        nets = self._get_tenant_nets(tenant)
        self._verify_net_and_port(network, port, nets)
        nets[network]['ports'][port]['attachment'] = None
