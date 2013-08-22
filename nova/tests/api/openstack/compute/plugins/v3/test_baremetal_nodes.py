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

from nova.api.openstack.compute.plugins.v3 import baremetal_nodes
from nova import context
from nova import exception
from nova import test
from nova.virt.baremetal import db


class FakeRequest(object):

    def __init__(self, context):
        self.environ = {"nova.context": context}


class BareMetalNodesTest(test.TestCase):

    def setUp(self):
        super(BareMetalNodesTest, self).setUp()

        self.context = context.get_admin_context()
        self.controller = baremetal_nodes.BareMetalNodeController()
        self.request = FakeRequest(self.context)

    def test_create(self):
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
        response = node.copy()
        response['id'] = 100
        del response['pm_password']
        response['instance_uuid'] = None
        self.mox.StubOutWithMock(db, 'bm_node_create')
        db.bm_node_create(self.context, node).AndReturn(response)
        self.mox.ReplayAll()
        res_dict = self.controller.create(self.request, {'node': node})
        self.assertEqual({'node': response}, res_dict)
        self.assertEqual(self.controller.create.wsgi_code, 201)

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
        db.bm_interface_get_all_by_bm_node_id(self.context, 2).\
                AndReturn(interfaces)
        self.mox.ReplayAll()
        res_dict = self.controller.index(self.request)
        self.assertEqual(2, len(res_dict['nodes']))
        self.assertEqual([], res_dict['nodes'][0]['interfaces'])
        self.assertEqual(2, len(res_dict['nodes'][1]['interfaces']))

    def test_show(self):
        node_id = 1
        node = {'id': node_id}
        interfaces = [{'id': 1, 'address': '11:11:11:11:11:11'},
                      {'id': 2, 'address': '22:22:22:22:22:22'},
                      ]
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        db.bm_node_get(self.context, node_id).AndReturn(node)
        db.bm_interface_get_all_by_bm_node_id(self.context, node_id).\
                AndReturn(interfaces)
        self.mox.ReplayAll()
        res_dict = self.controller.show(self.request, node_id)
        self.assertEqual(node_id, res_dict['node']['id'])
        self.assertEqual(2, len(res_dict['node']['interfaces']))

    def test_show_no_interfaces(self):
        node_id = 1
        node = {'id': node_id}
        self.mox.StubOutWithMock(db, 'bm_node_get')
        self.mox.StubOutWithMock(db, 'bm_interface_get_all_by_bm_node_id')
        db.bm_node_get(self.context, node_id).AndReturn(node)
        db.bm_interface_get_all_by_bm_node_id(self.context, node_id).\
                AndRaise(exception.NodeNotFound(node_id=node_id))
        self.mox.ReplayAll()
        res_dict = self.controller.show(self.request, node_id)
        self.assertEqual(node_id, res_dict['node']['id'])
        self.assertEqual(0, len(res_dict['node']['interfaces']))

    def test_add_interface(self):
        node_id = 1
        address = '11:22:33:44:55:66'
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
