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

from webob import exc

from nova.api.openstack.compute.contrib import baremetal_nodes
from nova.api.openstack import extensions
from nova import context
from nova import exception
from nova import test
from nova.virt.baremetal import db


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


def fake_interface(**updates):
    interface = {
        'id': 1,
        'address': '11:11:11:11:11:11',
        'datapath_id': 2,
        'port_no': 3,
    }
    if updates:
        interface.update(updates)
    return interface


class BareMetalNodesTest(test.NoDBTestCase):

    def setUp(self):
        super(BareMetalNodesTest, self).setUp()

        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.context = context.get_admin_context()
        self.controller = baremetal_nodes.BareMetalNodeController(self.ext_mgr)
        self.request = FakeRequest(self.context)

    def _test_create(self, node, ext_status=False):
        response = node.copy()
        del response['pm_password']
        response['instance_uuid'] = None
        self.mox.StubOutWithMock(db, 'bm_node_create')
        db.bm_node_create(self.context, node).AndReturn(response)
        self.ext_mgr.is_loaded('os-baremetal-ext-status').AndReturn(ext_status)
        self.mox.ReplayAll()
        res_dict = self.controller.create(self.request, {'node': node})
        self.assertEqual({'node': response}, res_dict)

    def _test_show(self, node, ext_status=False):
        interfaces = [fake_interface(id=1, address='11:11:11:11:11:11'),
                      fake_interface(id=2, address='22:22:22:22:22:22'),
                      ]
        node.update(interfaces=interfaces)
        response = node.copy()
        del response['pm_password']
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        db.bm_node_get(self.context, node['id']).AndReturn(node)
        db.bm_interface_get_all_by_bm_node_id(self.context, node['id']).\
                AndReturn(interfaces)
        self.ext_mgr.is_loaded('os-baremetal-ext-status').AndReturn(ext_status)
        self.mox.ReplayAll()
        res_dict = self.controller.show(self.request, node['id'])
        self.assertEqual({'node': response}, res_dict)
        self.assertEqual(2, len(res_dict['node']['interfaces']))

    def _test_show_no_interfaces(self, ext_status=False):
        node_id = 1
        node = {'id': node_id}
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        db.bm_node_get(self.context, node_id).AndReturn(node)
        db.bm_interface_get_all_by_bm_node_id(self.context, node_id).\
                AndRaise(exception.NodeNotFound(node_id=node_id))
        self.ext_mgr.is_loaded('os-baremetal-ext-status').AndReturn(ext_status)
        self.mox.ReplayAll()
        res_dict = self.controller.show(self.request, node_id)
        self.assertEqual(node_id, res_dict['node']['id'])
        self.assertEqual(0, len(res_dict['node']['interfaces']))

    def _test_index(self, ext_status=False):
        nodes = [{'id': 1},
                 {'id': 2},
                 ]
        interfaces = [{'id': 1, 'address': '11:11:11:11:11:11'},
                      {'id': 2, 'address': '22:22:22:22:22:22'},
                      ]
        self.mox.StubOutWithMock(db, 'bm_node_get_all')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        db.bm_node_get_all(self.context).AndReturn(nodes)
        db.bm_interface_get_all_by_bm_node_id(self.context, 1).\
                AndRaise(exception.NodeNotFound(node_id=1))
        for n in nodes:
            self.ext_mgr.is_loaded('os-baremetal-ext-status').\
                AndReturn(ext_status)
        db.bm_interface_get_all_by_bm_node_id(self.context, 2).\
                AndReturn(interfaces)
        self.mox.ReplayAll()
        res_dict = self.controller.index(self.request)
        self.assertEqual(2, len(res_dict['nodes']))
        self.assertEqual([], res_dict['nodes'][0]['interfaces'])
        self.assertEqual(2, len(res_dict['nodes'][1]['interfaces']))

    def test_create(self):
        node = fake_node(id=100)
        self._test_create(node)

    def test_create_ext_status(self):
        node = fake_node_ext_status(id=100)
        self._test_create(node, ext_status=True)

    def test_create_with_prov_mac_address(self):
        node = {
            'service_host': "host",
            'cpus': 8,
            'memory_mb': 8192,
            'local_gb': 128,
            'pm_address': "10.1.2.3",
            'pm_user': "pm_user",
            'pm_password': "pm_pass",
            'terminal_port': 8000,
            'interfaces': [],
        }
        intf = {
            'address': '1a:B2:3C:4d:e5:6f',
            'datapath_id': None,
            'id': None,
            'port_no': None,
        }

        request = node.copy()
        request['prov_mac_address'] = intf['address']

        db_node = node.copy()
        db_node['id'] = 100

        response = node.copy()
        response.update(id=db_node['id'],
                        instance_uuid=None,
                        interfaces=[intf])
        del response['pm_password']

        self.mox.StubOutWithMock(db, 'bm_node_create')
        self.mox.StubOutWithMock(db, 'bm_interface_create')
        self.mox.StubOutWithMock(db, 'bm_interface_get')
        db.bm_node_create(self.context, node).AndReturn(db_node)
        self.ext_mgr.is_loaded('os-baremetal-ext-status').AndReturn(False)
        db.bm_interface_create(self.context,
                               bm_node_id=db_node['id'],
                               address=intf['address'],
                               datapath_id=intf['datapath_id'],
                               port_no=intf['port_no']).AndReturn(1000)
        db.bm_interface_get(self.context, 1000).AndReturn(intf)
        self.mox.ReplayAll()
        res_dict = self.controller.create(self.request, {'node': request})
        self.assertEqual({'node': response}, res_dict)

    def test_create_with_invalid_prov_mac_address(self):
        node = {
            'service_host': "host",
            'cpus': 8,
            'memory_mb': 8192,
            'local_gb': 128,
            'pm_address': "10.1.2.3",
            'pm_user': "pm_user",
            'pm_password': "pm_pass",
            'terminal_port': 8000,
            'prov_mac_address': 'INVALID!!',
        }
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller.create,
                          self.request, {'node': node})

    def test_delete(self):
        self.mox.StubOutWithMock(db, 'bm_node_destroy')
        db.bm_node_destroy(self.context, 1)
        self.mox.ReplayAll()
        self.controller.delete(self.request, 1)

    def test_delete_node_not_found(self):
        self.mox.StubOutWithMock(db, 'bm_node_destroy')
        db.bm_node_destroy(self.context, 1).\
                AndRaise(exception.NodeNotFound(node_id=1))
        self.mox.ReplayAll()
        self.assertRaises(
                exc.HTTPNotFound,
                self.controller.delete,
                self.request,
                1)

    def test_index(self):
        self._test_index()

    def test_index_ext_status(self):
        self._test_index(ext_status=True)

    def test_show(self):
        node = fake_node(id=1)
        self._test_show(node)

    def test_show_ext_status(self):
        node = fake_node_ext_status(id=1)
        self._test_show(node, ext_status=True)

    def test_show_no_interfaces(self):
        self._test_show_no_interfaces()

    def test_show_no_interfaces_ext_status(self):
        self._test_show_no_interfaces(ext_status=True)

    def test_add_interface(self):
        node_id = 1
        address = '11:22:33:ab:cd:ef'
        body = {'add_interface': {'address': address}}
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_create')
        self.mox.StubOutWithMock(db, 'bm_interface_get')
        db.bm_node_get(self.context, node_id)
        db.bm_interface_create(self.context,
                               bm_node_id=node_id,
                               address=address,
                               datapath_id=None,
                               port_no=None).\
                               AndReturn(12345)
        db.bm_interface_get(self.context, 12345).\
                AndReturn({'id': 12345, 'address': address})
        self.mox.ReplayAll()
        res_dict = self.controller._add_interface(self.request, node_id, body)
        self.assertEqual(12345, res_dict['interface']['id'])
        self.assertEqual(address, res_dict['interface']['address'])

    def test_add_interface_invalid_address(self):
        node_id = 1
        body = {'add_interface': {'address': ''}}
        self.mox.StubOutWithMock(db, 'bm_node_get')
        db.bm_node_get(self.context, node_id)
        self.mox.ReplayAll()
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._add_interface,
                          self.request,
                          node_id,
                          body)

    def test_remove_interface(self):
        node_id = 1
        interfaces = [{'id': 1},
                      {'id': 2},
                      {'id': 3},
                      ]
        body = {'remove_interface': {'id': 2}}
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        self.mox.StubOutWithMock(db, 'bm_interface_destroy')
        db.bm_node_get(self.context, node_id)
        db.bm_interface_get_all_by_bm_node_id(self.context, node_id).\
                AndReturn(interfaces)
        db.bm_interface_destroy(self.context, 2)
        self.mox.ReplayAll()
        self.controller._remove_interface(self.request, node_id, body)

    def test_remove_interface_by_address(self):
        node_id = 1
        interfaces = [{'id': 1, 'address': '11:11:11:11:11:11'},
                      {'id': 2, 'address': '22:22:22:22:22:22'},
                      {'id': 3, 'address': '33:33:33:33:33:33'},
                      ]
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        self.mox.StubOutWithMock(db, 'bm_interface_destroy')
        db.bm_node_get(self.context, node_id)
        db.bm_interface_get_all_by_bm_node_id(self.context, node_id).\
                AndReturn(interfaces)
        db.bm_interface_destroy(self.context, 2)
        self.mox.ReplayAll()
        body = {'remove_interface': {'address': '22:22:22:22:22:22'}}
        self.controller._remove_interface(self.request, node_id, body)

    def test_remove_interface_no_id_no_address(self):
        node_id = 1
        self.mox.StubOutWithMock(db, 'bm_node_get')
        db.bm_node_get(self.context, node_id)
        self.mox.ReplayAll()
        body = {'remove_interface': {}}
        self.assertRaises(exc.HTTPBadRequest,
                          self.controller._remove_interface,
                          self.request,
                          node_id,
                          body)

    def test_add_interface_node_not_found(self):
        node_id = 1
        self.mox.StubOutWithMock(db, 'bm_node_get')
        db.bm_node_get(self.context, node_id).\
                AndRaise(exception.NodeNotFound(node_id=node_id))
        self.mox.ReplayAll()
        body = {'add_interface': {'address': '11:11:11:11:11:11'}}
        self.assertRaises(exc.HTTPNotFound,
                          self.controller._add_interface,
                          self.request,
                          node_id,
                          body)

    def test_remove_interface_node_not_found(self):
        node_id = 1
        self.mox.StubOutWithMock(db, 'bm_node_get')
        db.bm_node_get(self.context, node_id).\
                AndRaise(exception.NodeNotFound(node_id=node_id))
        self.mox.ReplayAll()
        body = {'remove_interface': {'address': '11:11:11:11:11:11'}}
        self.assertRaises(exc.HTTPNotFound,
                          self.controller._remove_interface,
                          self.request,
                          node_id,
                          body)

    def test_is_valid_mac(self):
        self.assertFalse(baremetal_nodes.is_valid_mac(None))
        self.assertTrue(baremetal_nodes.is_valid_mac("52:54:00:cf:2d:31"))
        self.assertTrue(baremetal_nodes.is_valid_mac(u"52:54:00:cf:2d:31"))
        self.assertFalse(baremetal_nodes.is_valid_mac("127.0.0.1"))
        self.assertFalse(baremetal_nodes.is_valid_mac("not:a:mac:address"))
        self.assertFalse(baremetal_nodes.is_valid_mac("52-54-00-cf-2d-31"))
        self.assertFalse(baremetal_nodes.is_valid_mac("5254.00cf.2d31"))
        self.assertFalse(baremetal_nodes.is_valid_mac("52:54:0:cf:2d:31"))
        self.assertFalse(baremetal_nodes.is_valid_mac("aa bb cc dd ee ff"))
        self.assertTrue(baremetal_nodes.is_valid_mac("AA:BB:CC:DD:EE:FF"))
        self.assertFalse(baremetal_nodes.is_valid_mac("AA BB CC DD EE FF"))
        self.assertFalse(baremetal_nodes.is_valid_mac("AA-BB-CC-DD-EE-FF"))
