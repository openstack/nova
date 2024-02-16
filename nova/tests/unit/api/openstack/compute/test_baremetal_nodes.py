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

import fixtures
from openstack import exceptions as sdk_exc
from webob import exc

from nova.api.openstack.compute import baremetal_nodes
from nova import context
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.virt.ironic import utils as ironic_utils


class BareMetalNodesTest(test.NoDBTestCase):
    mod = baremetal_nodes

    def setUp(self):
        super().setUp()

        self._setup()
        self.context = context.get_admin_context()
        self.request = fakes.HTTPRequest.blank('', use_admin_context=True)

        # stub out openstacksdk
        self.mock_conn = self.useFixture(
            fixtures.MockPatchObject(self.controller, '_ironic_connection'),
        ).mock

    def _setup(self):
        self.controller = baremetal_nodes.BareMetalNodeController()

    def test_index_ironic(self):
        properties = {'cpus': 2, 'memory_mb': 1024, 'local_gb': 20}
        node = ironic_utils.get_test_node(properties=properties)
        self.mock_conn.nodes.return_value = iter([node])

        res_dict = self.controller.index(self.request)

        expected_output = {'nodes':
                            [{'memory_mb': properties['memory_mb'],
                             'host': 'IRONIC MANAGED',
                             'disk_gb': properties['local_gb'],
                             'interfaces': [],
                             'task_state': 'available',
                             'id': node.id,
                             'cpus': properties['cpus']}]}
        self.assertEqual(expected_output, res_dict)
        self.mock_conn.nodes.assert_called_once_with(details=True)

    def test_index_ironic_missing_properties(self):
        properties = {'cpus': 2}
        node = ironic_utils.get_test_node(properties=properties)
        self.mock_conn.nodes.return_value = iter([node])

        res_dict = self.controller.index(self.request)

        expected_output = {'nodes':
                            [{'memory_mb': 0,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': 0,
                             'interfaces': [],
                             'task_state': 'available',
                             'id': node.id,
                             'cpus': properties['cpus']}]}
        self.assertEqual(expected_output, res_dict)
        self.mock_conn.nodes.assert_called_once_with(details=True)

    def test_show_ironic(self):
        properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
        node = ironic_utils.get_test_node(properties=properties)
        port = ironic_utils.get_test_port()
        self.mock_conn.get_node.return_value = node
        self.mock_conn.ports.return_value = iter([port])

        res_dict = self.controller.show(self.request, node.id)

        expected_output = {'node':
                            {'memory_mb': properties['memory_mb'],
                             'instance_uuid': None,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': properties['local_gb'],
                             'interfaces': [{'address': port.address}],
                             'task_state': 'available',
                             'id': node.id,
                             'cpus': properties['cpus']}}
        self.assertEqual(expected_output, res_dict)
        self.mock_conn.get_node.assert_called_once_with(node.id)
        self.mock_conn.ports.assert_called_once_with(node=node.id)

    def test_show_ironic_no_properties(self):
        properties = {}
        node = ironic_utils.get_test_node(properties=properties)
        port = ironic_utils.get_test_port()
        self.mock_conn.get_node.return_value = node
        self.mock_conn.ports.return_value = iter([port])

        res_dict = self.controller.show(self.request, node.id)

        expected_output = {'node':
                            {'memory_mb': 0,
                             'instance_uuid': None,
                             'host': 'IRONIC MANAGED',
                             'disk_gb': 0,
                             'interfaces': [{'address': port.address}],
                             'task_state': 'available',
                             'id': node.id,
                             'cpus': 0}}
        self.assertEqual(expected_output, res_dict)
        self.mock_conn.get_node.assert_called_once_with(node.id)
        self.mock_conn.ports.assert_called_once_with(node=node.id)

    def test_show_ironic_no_interfaces(self):
        properties = {'cpus': 1, 'memory_mb': 512, 'local_gb': 10}
        node = ironic_utils.get_test_node(properties=properties)
        self.mock_conn.get_node.return_value = node
        self.mock_conn.ports.return_value = iter([])

        res_dict = self.controller.show(self.request, node.id)

        self.assertEqual([], res_dict['node']['interfaces'])
        self.mock_conn.get_node.assert_called_once_with(node.id)
        self.mock_conn.ports.assert_called_once_with(node=node.id)

    def test_show_ironic_node_not_found(self):
        self.mock_conn.get_node.side_effect = sdk_exc.NotFoundException()

        error = self.assertRaises(
            exc.HTTPNotFound,
            self.controller.show,
            self.request, 'fake-uuid',
        )

        self.assertIn('fake-uuid', str(error))

    def test_create_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create,
                          self.request, body={'node': object()})

    def test_delete_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.delete,
                          self.request, 'fake-id')

    def test_add_interface_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._add_interface,
                          self.request, 'fake-id', body={})

    def test_remove_interface_ironic_not_supported(self):
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._remove_interface,
                          self.request, 'fake-id', body={})


class BareMetalNodesTestV236(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.controller = baremetal_nodes.BareMetalNodeController()
        self.req = fakes.HTTPRequest.blank('', version='2.36')

    def test_all_apis_return_not_found(self):
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.show, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.index, self.req)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.create, self.req, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._add_interface, self.req, fakes.FAKE_UUID, {})
        self.assertRaises(exception.VersionNotFoundForAPIMethod,
            self.controller._remove_interface, self.req, fakes.FAKE_UUID, {})
