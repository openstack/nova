# Copyright (c) 2013 NTT DOCOMO, INC.
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


from ironicclient import exc as ironic_exc
import mock
import six
from webob import exc

from nova.api.openstack.compute import baremetal_nodes \
        as b_nodes_v21
from nova.api.openstack.compute.legacy_v2.contrib import baremetal_nodes \
        as b_nodes_v2
from nova.api.openstack import extensions
from nova import context
from nova import test
from nova.tests.unit.virt.ironic import utils as ironic_utils


class FakeRequest(object):

    def __init__(self, context):
        self.environ = {"nova.context": context}


def fake_node(**updates):
    node = {
        'id': 1,
        'service_host': "host",
        'cpus': 8,
        'memory_mb': 8192,
        'local_gb': 128,
        'pm_address': "10.1.2.3",
        'pm_user': "pm_user",
        'pm_password': "pm_pass",
        'terminal_port': 8000,
        'interfaces': [],
        'instance_uuid': 'fake-instance-uuid',
    }
    if updates:
        node.update(updates)
    return node


def fake_node_ext_status(**updates):
    node = fake_node(uuid='fake-uuid',
                     task_state='fake-task-state',
                     updated_at='fake-updated-at',
                     pxe_config_path='fake-pxe-config-path')
    if updates:
        node.update(updates)
    return node


FAKE_IRONIC_CLIENT = ironic_utils.FakeClient()


@mock.patch.object(b_nodes_v21, '_get_ironic_client',
                   lambda *_: FAKE_IRONIC_CLIENT)
class BareMetalNodesTestV21(test.NoDBTestCase):
    mod = b_nodes_v21

    def setUp(self):
        super(BareMetalNodesTestV21, self).setUp()

        self._setup()
        self.context = context.get_admin_context()
        self.request = FakeRequest(self.context)

    def _setup(self):
        self.controller = b_nodes_v21.BareMetalNodeController()

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list')
    def test_index_ironic(self, mock_list):
        properties = {'cpus': 2, 'memory_mb': 1024, 'local_gb': 20}
        node = ironic_utils.get_test_node(properties=properties)
        mock_list.return_value = [node]

        res_dict = self.controller.index(self.request)
        expected_output = {'nodes':
                            [{'memory_mb': properties['memory_mb'],
                             'host': 'IRONIC MANAGED',
                             'disk_gb': properties['local_gb'],
                             'interfaces': [],
                             'task_state': None,
                             'id': node.uuid,
                             'cpus': properties['cpus']}]}
        self.assertEqual(expected_output, res_dict)
        mock_list.assert_called_once_with(detail=True)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list')
    def test_index_ironic_missing_properties(self, mock_list):
        properties = {'cpus': 2}
        node = ironic_utils.get_test_node(properties=properties)
        mock_list.return_value = [node]

        res_dict = self.controller.index(self.request)
        expected_output = {'nodes':
                            [{'memory_mb': 0,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': 0,
                             'interfaces': [],
                             'task_state': None,
                             'id': node.uuid,
                             'cpus': properties['cpus']}]}
        self.assertEqual(expected_output, res_dict)
        mock_list.assert_called_once_with(detail=True)

    def test_index_ironic_not_implemented(self):
        with mock.patch.object(self.mod, 'ironic_client', None):
            self.assertRaises(exc.HTTPNotImplemented,
                              self.controller.index,
                              self.request)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'get')
    def test_show_ironic(self, mock_get, mock_list_ports):
        properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
        node = ironic_utils.get_test_node(properties=properties)
        port = ironic_utils.get_test_port()
        mock_get.return_value = node
        mock_list_ports.return_value = [port]

        res_dict = self.controller.show(self.request, node.uuid)
        expected_output = {'node':
                            {'memory_mb': properties['memory_mb'],
                             'instance_uuid': None,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': properties['local_gb'],
                             'interfaces': [{'address': port.address}],
                             'task_state': None,
                             'id': node.uuid,
                             'cpus': properties['cpus']}}
        self.assertEqual(expected_output, res_dict)
        mock_get.assert_called_once_with(node.uuid)
        mock_list_ports.assert_called_once_with(node.uuid)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'get')
    def test_show_ironic_no_properties(self, mock_get, mock_list_ports):
        properties = {}
        node = ironic_utils.get_test_node(properties=properties)
        port = ironic_utils.get_test_port()
        mock_get.return_value = node
        mock_list_ports.return_value = [port]

        res_dict = self.controller.show(self.request, node.uuid)
        expected_output = {'node':
                            {'memory_mb': 0,
                             'instance_uuid': None,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': 0,
                             'interfaces': [{'address': port.address}],
                             'task_state': None,
                             'id': node.uuid,
                             'cpus': 0}}
        self.assertEqual(expected_output, res_dict)
        mock_get.assert_called_once_with(node.uuid)
        mock_list_ports.assert_called_once_with(node.uuid)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'list_ports')
    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'get')
    def test_show_ironic_no_interfaces(self, mock_get, mock_list_ports):
        properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
        node = ironic_utils.get_test_node(properties=properties)
        mock_get.return_value = node
        mock_list_ports.return_value = []

        res_dict = self.controller.show(self.request, node.uuid)
        self.assertEqual([], res_dict['node']['interfaces'])
        mock_get.assert_called_once_with(node.uuid)
        mock_list_ports.assert_called_once_with(node.uuid)

    @mock.patch.object(FAKE_IRONIC_CLIENT.node, 'get',
                       side_effect=ironic_exc.NotFound())
    def test_show_ironic_node_not_found(self, mock_get):
        error = self.assertRaises(exc.HTTPNotFound, self.controller.show,
                                  self.request, 'fake-uuid')
        self.assertIn('fake-uuid', six.text_type(error))

    def test_show_ironic_not_implemented(self):
        with mock.patch.object(self.mod, 'ironic_client', None):
            properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
            node = ironic_utils.get_test_node(properties=properties)
            self.assertRaises(exc.HTTPNotImplemented, self.controller.show,
                              self.request, node.uuid)

    def test_create_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create,
                          self.request, {'node': object()})

    def test_delete_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.delete,
                          self.request, 'fake-id')

    def test_add_interface_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._add_interface,
                          self.request, 'fake-id', 'fake-body')

    def test_remove_interface_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._remove_interface,
                          self.request, 'fake-id', 'fake-body')


@mock.patch.object(b_nodes_v2, '_get_ironic_client',
                   lambda *_: FAKE_IRONIC_CLIENT)
class BareMetalNodesTestV2(BareMetalNodesTestV21):
    mod = b_nodes_v2

    def _setup(self):
        self.ext_mgr = extensions.ExtensionManager()
        self.ext_mgr.extensions = {}
        self.controller = b_nodes_v2.BareMetalNodeController(self.ext_mgr)
