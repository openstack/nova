# Copyright 2015 IBM Corp.
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

import mock

from nova.tests.functional.api_sample_tests import api_sample_base


class FakeNode(object):
    def __init__(self, uuid='058d27fa-241b-445a-a386-08c04f96db43'):
        self.uuid = uuid
        self.provision_state = 'active'
        self.properties = {'cpus': '2',
                           'memory_mb': '1024',
                           'local_gb': '10'}
        self.instance_uuid = '1ea4e53e-149a-4f02-9515-590c9fb2315a'


class NodeManager(object):
    def list(self, detail=False):
        return [FakeNode(), FakeNode('e2025409-f3ce-4d6a-9788-c565cf3b1b1c')]

    def get(self, id):
        return FakeNode(id)

    def list_ports(self, id):
        return []


class fake_client(object):
    node = NodeManager()


class BareMetalNodesSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-baremetal-nodes"

    @mock.patch("nova.api.openstack.compute.baremetal_nodes"
                "._get_ironic_client")
    def test_baremetal_nodes_list(self, mock_get_irc):
        mock_get_irc.return_value = fake_client()

        response = self._do_get('os-baremetal-nodes')
        self._verify_response('baremetal-node-list-resp', {}, response, 200)

    @mock.patch("nova.api.openstack.compute.baremetal_nodes"
                "._get_ironic_client")
    def test_baremetal_nodes_get(self, mock_get_irc):
        mock_get_irc.return_value = fake_client()

        response = self._do_get('os-baremetal-nodes/'
                                '058d27fa-241b-445a-a386-08c04f96db43')
        self._verify_response('baremetal-node-get-resp', {}, response, 200)
