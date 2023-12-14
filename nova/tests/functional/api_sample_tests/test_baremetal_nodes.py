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

from unittest import mock

from openstack.baremetal.v1 import _proxy as baremetal_proxy
from openstack.baremetal.v1 import node

from nova.tests.functional.api_sample_tests import api_sample_base


fake_nodes = [
    node.Node(
        id=id_,
        provision_state='active',
        properties={
            'cpus': '2',
            'memory_mb': '1024',
            'local_gb': '10',
        },
        instance_id='1ea4e53e-149a-4f02-9515-590c9fb2315a',
    ) for id_ in (
        '058d27fa-241b-445a-a386-08c04f96db43',
        'e2025409-f3ce-4d6a-9788-c565cf3b1b1c',
    )
]


def nodes(*args, **kwargs):
    for fake_node in fake_nodes:
        yield fake_node


def get_node(*args, **kwargs):
    return fake_nodes[0]


def ports(*args, **kwargs):
    # return an empty generator
    yield from ()


fake_client = mock.create_autospec(baremetal_proxy.Proxy)
fake_client.nodes.side_effect = nodes
fake_client.get_node.side_effect = get_node
fake_client.ports.side_effect = ports


@mock.patch(
    "nova.api.openstack.compute.baremetal_nodes"
    ".BareMetalNodeController.ironic_connection",
    new_callable=mock.PropertyMock,
    return_value=fake_client,
)
class BareMetalNodesSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-baremetal-nodes"

    def test_baremetal_nodes_list(self, mock_get_irc):
        response = self._do_get('os-baremetal-nodes')
        self._verify_response('baremetal-node-list-resp', {}, response, 200)

    def test_baremetal_nodes_get(self, mock_get_irc):
        response = self._do_get('os-baremetal-nodes/'
                                '058d27fa-241b-445a-a386-08c04f96db43')
        self._verify_response('baremetal-node-get-resp', {}, response, 200)
