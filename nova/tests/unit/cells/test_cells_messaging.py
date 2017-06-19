# Copyright (c) 2012 Rackspace Hosting
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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
"""
Tests For Cells Messaging module
"""

import mock
from mox3 import mox
import oslo_messaging
from oslo_serialization import jsonutils
from oslo_utils import timeutils

from nova.cells import messaging
from nova.cells import rpcapi as cells_rpcapi
from nova.cells import utils as cells_utils
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import base as objects_base
from nova.objects import fields as objects_fields
from nova import rpc
from nova import test
from nova.tests.unit.cells import fakes
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_server_actions
from nova.tests import uuidsentinel as uuids

CONF = nova.conf.CONF


class CellsMessageClassesTestCase(test.NoDBTestCase):
    """Test case for the main Cells Message classes."""
    def setUp(self):
        super(CellsMessageClassesTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self.our_name = 'api-cell'
        self.msg_runner = fakes.get_message_runner(self.our_name)
        self.state_manager = self.msg_runner.state_manager

    def test_reverse_path(self):
        path = 'a!b!c!d'
        expected = 'd!c!b!a'
        rev_path = messaging._reverse_path(path)
        self.assertEqual(expected, rev_path)

    def test_response_cell_name_from_path(self):
        # test array with tuples of inputs/expected outputs
        test_paths = [('cell1', 'cell1'),
                      ('cell1!cell2', 'cell2!cell1'),
                      ('cell1!cell2!cell3', 'cell3!cell2!cell1')]

        for test_input, expected_output in test_paths:
            self.assertEqual(expected_output,
                    messaging._response_cell_name_from_path(test_input))

    def test_response_cell_name_from_path_neighbor_only(self):
        # test array with tuples of inputs/expected outputs
        test_paths = [('cell1', 'cell1'),
                      ('cell1!cell2', 'cell2!cell1'),
                      ('cell1!cell2!cell3', 'cell3!cell2')]

        for test_input, expected_output in test_paths:
            self.assertEqual(expected_output,
                    messaging._response_cell_name_from_path(test_input,
                            neighbor_only=True))

    def test_response_to_json_and_from_json(self):
        fake_uuid = uuids.fake
        response = messaging.Response(self.ctxt, 'child-cell!api-cell',
                                      objects.Instance(id=1, uuid=fake_uuid),
                                      False)
        json_response = response.to_json()
        deserialized_response = messaging.Response.from_json(self.ctxt,
                                                             json_response)
        obj = deserialized_response.value
        self.assertIsInstance(obj, objects.Instance)
        self.assertEqual(1, obj.id)
        self.assertEqual(fake_uuid, obj.uuid)

    def test_targeted_message(self):
        self.flags(max_hop_count=99, group='cells')
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual(self.ctxt, tgt_message.ctxt)
        self.assertEqual(method, tgt_message.method_name)
        self.assertEqual(method_kwargs, tgt_message.method_kwargs)
        self.assertEqual(direction, tgt_message.direction)
        self.assertEqual(target_cell, target_cell)
        self.assertFalse(tgt_message.fanout)
        self.assertFalse(tgt_message.need_response)
        self.assertEqual(self.our_name, tgt_message.routing_path)
        self.assertEqual(1, tgt_message.hop_count)
        self.assertEqual(99, tgt_message.max_hop_count)
        self.assertFalse(tgt_message.is_broadcast)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        child_cell = self.state_manager.get_child_cell('child-cell2')
        self.assertEqual(child_cell, next_hop)

    def test_create_targeted_message_with_response(self):
        self.flags(max_hop_count=99, group='cells')
        our_name = 'child-cell1'
        target_cell = 'child-cell1!api-cell'
        msg_runner = fakes.get_message_runner(our_name)
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        tgt_message = messaging._TargetedMessage(msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        self.assertEqual(self.ctxt, tgt_message.ctxt)
        self.assertEqual(method, tgt_message.method_name)
        self.assertEqual(method_kwargs, tgt_message.method_kwargs)
        self.assertEqual(direction, tgt_message.direction)
        self.assertEqual(target_cell, target_cell)
        self.assertFalse(tgt_message.fanout)
        self.assertTrue(tgt_message.need_response)
        self.assertEqual(our_name, tgt_message.routing_path)
        self.assertEqual(1, tgt_message.hop_count)
        self.assertEqual(99, tgt_message.max_hop_count)
        self.assertFalse(tgt_message.is_broadcast)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        parent_cell = msg_runner.state_manager.get_parent_cell('api-cell')
        self.assertEqual(parent_cell, next_hop)

    def test_targeted_message_when_target_is_cell_state(self):
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        target_cell = self.state_manager.get_child_cell('child-cell2')
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual('api-cell!child-cell2', tgt_message.target_cell)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        self.assertEqual(target_cell, next_hop)

    def test_targeted_message_when_target_cell_state_is_me(self):
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        target_cell = self.state_manager.get_my_state()
        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        self.assertEqual('api-cell', tgt_message.target_cell)
        # Correct next hop?
        next_hop = tgt_message._get_next_hop()
        self.assertEqual(target_cell, next_hop)

    def test_create_broadcast_message(self):
        self.flags(max_hop_count=99, group='cells')
        self.flags(name='api-cell', max_hop_count=99, group='cells')
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'
        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction)
        self.assertEqual(self.ctxt, bcast_message.ctxt)
        self.assertEqual(method, bcast_message.method_name)
        self.assertEqual(method_kwargs, bcast_message.method_kwargs)
        self.assertEqual(direction, bcast_message.direction)
        self.assertFalse(bcast_message.fanout)
        self.assertFalse(bcast_message.need_response)
        self.assertEqual(self.our_name, bcast_message.routing_path)
        self.assertEqual(1, bcast_message.hop_count)
        self.assertEqual(99, bcast_message.max_hop_count)
        self.assertTrue(bcast_message.is_broadcast)
        # Correct next hops?
        next_hops = bcast_message._get_next_hops()
        child_cells = self.state_manager.get_child_cells()
        self.assertEqual(child_cells, next_hops)

    def test_create_broadcast_message_with_response(self):
        self.flags(max_hop_count=99, group='cells')
        our_name = 'child-cell1'
        msg_runner = fakes.get_message_runner(our_name)
        method = 'fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        bcast_message = messaging._BroadcastMessage(msg_runner, self.ctxt,
                method, method_kwargs, direction, need_response=True)
        self.assertEqual(self.ctxt, bcast_message.ctxt)
        self.assertEqual(method, bcast_message.method_name)
        self.assertEqual(method_kwargs, bcast_message.method_kwargs)
        self.assertEqual(direction, bcast_message.direction)
        self.assertFalse(bcast_message.fanout)
        self.assertTrue(bcast_message.need_response)
        self.assertEqual(our_name, bcast_message.routing_path)
        self.assertEqual(1, bcast_message.hop_count)
        self.assertEqual(99, bcast_message.max_hop_count)
        self.assertTrue(bcast_message.is_broadcast)
        # Correct next hops?
        next_hops = bcast_message._get_next_hops()
        parent_cells = msg_runner.state_manager.get_parent_cells()
        self.assertEqual(parent_cells, next_hops)

    def test_self_targeted_message(self):
        target_cell = 'api-cell'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'api-cell', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_child_targeted_message(self):
        target_cell = 'api-cell!child-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'child-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_child_targeted_message_with_object(self):
        target_cell = 'api-cell!child-cell1'
        method = 'our_fake_method'
        direction = 'down'

        call_info = {}

        class CellsMsgingTestObject(objects_base.NovaObject):
            """Test object.  We just need 1 field in order to test
            that this gets serialized properly.
            """
            fields = {'test': objects_fields.StringField()}

        objects_base.NovaObjectRegistry.register(CellsMsgingTestObject)

        test_obj = CellsMsgingTestObject()
        test_obj.test = 'meow'

        method_kwargs = dict(obj=test_obj, arg1=1, arg2=2)

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'child-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(target_cell, call_info['routing_path'])
        self.assertEqual(3, len(call_info['kwargs']))
        self.assertEqual(1, call_info['kwargs']['arg1'])
        self.assertEqual(2, call_info['kwargs']['arg2'])
        # Verify we get a new object with what we expect.
        obj = call_info['kwargs']['obj']
        self.assertIsInstance(obj, CellsMsgingTestObject)
        self.assertNotEqual(id(test_obj), id(obj))
        self.assertEqual(test_obj.test, obj.test)

    def test_grandchild_targeted_message(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell)
        tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])

    def test_grandchild_targeted_message_with_response(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        call_info = {}

        def our_fake_method(message, **kwargs):
            call_info['context'] = message.ctxt
            call_info['routing_path'] = message.routing_path
            call_info['kwargs'] = kwargs
            return 'our_fake_response'

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()

        self.assertEqual(self.ctxt, call_info['context'])
        self.assertEqual(method_kwargs, call_info['kwargs'])
        self.assertEqual(target_cell, call_info['routing_path'])
        self.assertFalse(response.failure)
        self.assertEqual('our_fake_response', response.value_or_raise())

    def test_grandchild_targeted_message_with_error(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('this should be returned')

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(test.TestingException, response.value_or_raise)

    def test_grandchild_targeted_message_max_hops(self):
        self.flags(max_hop_count=2, group='cells')
        target_cell = 'api-cell!child-cell2!grandchild-cell1'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('should not be reached')

        fakes.stub_tgt_method(self, 'grandchild-cell1', 'our_fake_method',
                our_fake_method)

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellMaxHopCountReached,
                response.value_or_raise)

    def test_targeted_message_invalid_cell(self):
        target_cell = 'api-cell!child-cell2!grandchild-cell4'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellRoutingInconsistency,
                response.value_or_raise)

    def test_targeted_message_invalid_cell2(self):
        target_cell = 'unknown-cell!child-cell2'
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        tgt_message = messaging._TargetedMessage(self.msg_runner,
                                                  self.ctxt, method,
                                                  method_kwargs, direction,
                                                  target_cell,
                                                  need_response=True)
        response = tgt_message.process()
        self.assertTrue(response.failure)
        self.assertRaises(exception.CellRoutingInconsistency,
                response.value_or_raise)

    def test_targeted_message_target_cell_none(self):
        target_cell = None
        method = 'our_fake_method'
        method_kwargs = dict(arg=1, arg2=2)
        direction = 'down'

        self.assertRaises(exception.CellRoutingInconsistency,
                messaging._TargetedMessage, self.msg_runner, self.ctxt, method,
                method_kwargs, direction, target_cell, need_response=False)

    def test_broadcast_routing(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True)
        bcast_message.process()
        # fakes creates 8 cells (including ourself).
        self.assertEqual(8, len(cells))

    def test_broadcast_routing_up(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'up'
        msg_runner = fakes.get_message_runner('grandchild-cell3')

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(msg_runner, self.ctxt,
                                                    method, method_kwargs,
                                                    direction,
                                                    run_locally=True)
        bcast_message.process()
        # Paths are reversed, since going 'up'
        expected = set(['grandchild-cell3', 'grandchild-cell3!child-cell3',
                        'grandchild-cell3!child-cell3!api-cell'])
        self.assertEqual(expected, cells)

    def test_broadcast_routing_without_ourselves(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        cells = set()

        def our_fake_method(message, **kwargs):
            cells.add(message.routing_path)

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=False)
        bcast_message.process()
        # fakes creates 8 cells (including ourself).  So we should see
        # only 7 here.
        self.assertEqual(7, len(cells))

    def test_broadcast_routing_with_response(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(8, len(responses))
        for response in responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

    def test_broadcast_routing_with_response_max_hops(self):
        self.flags(max_hop_count=2, group='cells')
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        # Should only get responses from our immediate children (and
        # ourselves)
        self.assertEqual(5, len(responses))
        for response in responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

    def test_broadcast_routing_with_all_erroring(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method(message, **kwargs):
            raise test.TestingException('fake failure')

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(8, len(responses))
        for response in responses:
            self.assertTrue(response.failure)
            self.assertRaises(test.TestingException, response.value_or_raise)

    def test_broadcast_routing_with_two_erroring(self):
        method = 'our_fake_method'
        method_kwargs = dict(arg1=1, arg2=2)
        direction = 'down'

        def our_fake_method_failing(message, **kwargs):
            raise test.TestingException('fake failure')

        def our_fake_method(message, **kwargs):
            return 'response-%s' % message.routing_path

        fakes.stub_bcast_methods(self, 'our_fake_method', our_fake_method)
        fakes.stub_bcast_method(self, 'child-cell2', 'our_fake_method',
                                our_fake_method_failing)
        fakes.stub_bcast_method(self, 'grandchild-cell3', 'our_fake_method',
                                our_fake_method_failing)

        bcast_message = messaging._BroadcastMessage(self.msg_runner,
                                                    self.ctxt, method,
                                                    method_kwargs,
                                                    direction,
                                                    run_locally=True,
                                                    need_response=True)
        responses = bcast_message.process()
        self.assertEqual(8, len(responses))
        failure_responses = [resp for resp in responses if resp.failure]
        success_responses = [resp for resp in responses if not resp.failure]
        self.assertEqual(2, len(failure_responses))
        self.assertEqual(6, len(success_responses))

        for response in success_responses:
            self.assertFalse(response.failure)
            self.assertEqual('response-%s' % response.cell_name,
                    response.value_or_raise())

        for response in failure_responses:
            self.assertIn(response.cell_name, ['api-cell!child-cell2',
                    'api-cell!child-cell3!grandchild-cell3'])
            self.assertTrue(response.failure)
            self.assertRaises(test.TestingException, response.value_or_raise)


class CellsTargetedMethodsWithDatabaseTestCase(test.TestCase):
    """These tests access the database unlike the others."""

    def setUp(self):
        super(CellsTargetedMethodsWithDatabaseTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self._setup_attrs('api-cell', 'api-cell!child-cell2')

    def _setup_attrs(self, source_cell, target_cell):
        self.tgt_cell_name = target_cell
        self.src_msg_runner = fakes.get_message_runner(source_cell)

    def test_service_delete(self):
        fake_service = dict(id=42, host='fake_host', binary='nova-compute',
                            topic='compute')

        ctxt = self.ctxt.elevated()
        db.service_create(ctxt, fake_service)

        self.src_msg_runner.service_delete(
            ctxt, self.tgt_cell_name, fake_service['id'])
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, ctxt, fake_service['id'])


class CellsTargetedMethodsTestCase(test.NoDBTestCase):
    """Test case for _TargetedMessageMethods class.  Most of these
    tests actually test the full path from the MessageRunner through
    to the functionality of the message method.  Hits 2 birds with 1
    stone, even though it's a little more than a unit test.
    """
    def setUp(self):
        super(CellsTargetedMethodsTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self._setup_attrs('api-cell', 'api-cell!child-cell2')

    def _setup_attrs(self, source_cell, target_cell):
        self.tgt_cell_name = target_cell
        self.src_msg_runner = fakes.get_message_runner(source_cell)
        self.src_state_manager = self.src_msg_runner.state_manager
        tgt_shortname = target_cell.split('!')[-1]
        self.tgt_cell_mgr = fakes.get_cells_manager(tgt_shortname)
        self.tgt_msg_runner = self.tgt_cell_mgr.msg_runner
        self.tgt_scheduler = self.tgt_msg_runner.scheduler
        self.tgt_state_manager = self.tgt_msg_runner.state_manager
        methods_cls = self.tgt_msg_runner.methods_by_type['targeted']
        self.tgt_methods_cls = methods_cls
        self.tgt_compute_api = methods_cls.compute_api
        self.tgt_host_api = methods_cls.host_api
        self.tgt_db_inst = methods_cls.db
        self.tgt_c_rpcapi = methods_cls.compute_rpcapi

    def test_build_instances(self):
        build_inst_kwargs = {'filter_properties': {},
                             'key1': 'value1',
                             'key2': 'value2'}
        with mock.patch.object(self.tgt_scheduler,
                               'build_instances') as mock_build_instances:
            self.src_msg_runner.build_instances(self.ctxt, self.tgt_cell_name,
                                                build_inst_kwargs)
            mock_build_instances.assert_called_with(
                    test.MatchType(messaging._TargetedMessage),
                    build_inst_kwargs)

    def _run_compute_api_method(self, method_name):
        instance = fake_instance.fake_instance_obj(self.ctxt)
        method_info = {'method': method_name,
                       'method_args': (instance.uuid, 2, 3),
                       'method_kwargs': {'arg1': 'val1', 'arg2': 'val2'}}
        expected_attrs = ['metadata', 'system_metadata', 'security_groups',
                          'info_cache']

        @mock.patch.object(self.tgt_compute_api, method_name,
                return_value='fake-result')
        @mock.patch.object(objects.Instance, 'get_by_uuid',
                return_value=instance)
        def run_method(mock_get_by_uuid, mock_method):
            response = self.src_msg_runner.run_compute_api_method(
                    self.ctxt,
                    self.tgt_cell_name,
                    method_info,
                    True)
            result = response.value_or_raise()
            self.assertEqual('fake-result', result)

            mock_get_by_uuid.assert_called_once_with(self.ctxt, instance.uuid,
                    expected_attrs=expected_attrs)
            mock_method.assert_called_once_with(self.ctxt, instance, 2, 3,
                    arg1='val1', arg2='val2')

        run_method()

    def test_run_compute_api_method_expects_obj(self):
        # Run compute_api start method
        self._run_compute_api_method('start')

    def test_run_compute_api_method_shelve_with_info_cache(self):
        # Run compute_api shelve method as it requires info_cache and
        # metadata to be present in instance object
        self._run_compute_api_method('shelve')

    @mock.patch.object(objects.Instance, 'get_by_uuid')
    def test_run_compute_api_method_unknown_instance(self, mock_get_by_uuid):
        # Unknown instance should send a broadcast up that instance
        # is gone.
        instance = fake_instance.fake_instance_obj(self.ctxt)
        instance_uuid = instance.uuid
        method_info = {'method': 'reboot',
                       'method_args': (instance_uuid, 2, 3),
                       'method_kwargs': {'arg1': 'val1', 'arg2': 'val2'}}

        mock_get_by_uuid.side_effect = exception.InstanceNotFound(
                instance_id=instance_uuid)
        with mock.patch.object(self.tgt_msg_runner,
                               'instance_destroy_at_top') as des_top:
            response = self.src_msg_runner.run_compute_api_method(
                    self.ctxt,
                    self.tgt_cell_name,
                    method_info,
                    True)

            self.assertRaises(exception.InstanceNotFound,
                              response.value_or_raise)
            des_top.assert_called_with(self.ctxt,
                                       test.MatchType(objects.Instance))
            mock_get_by_uuid.assert_called_once_with(
                self.ctxt, instance.uuid,
                expected_attrs=['metadata', 'system_metadata',
                                'security_groups', 'info_cache'])

    def test_update_capabilities(self):
        # Route up to API
        self._setup_attrs('child-cell2', 'child-cell2!api-cell')
        capabs = {'cap1': set(['val1', 'val2']),
                  'cap2': set(['val3'])}
        # The list(set([])) seems silly, but we can't assume the order
        # of the list... This behavior should match the code we're
        # testing... which is check that a set was converted to a list.
        expected_capabs = {'cap1': list(set(['val1', 'val2'])),
                           'cap2': ['val3']}
        self.src_state_manager.get_our_capabilities = mock.Mock()
        self.src_state_manager.get_our_capabilities.return_value = capabs
        self.tgt_state_manager.update_cell_capabilities = mock.Mock()
        self.tgt_msg_runner.tell_parents_our_capabilities = mock.Mock()

        self.src_msg_runner.tell_parents_our_capabilities(self.ctxt)
        self.tgt_state_manager.update_cell_capabilities.\
                assert_called_with('child-cell2', expected_capabs)
        self.tgt_msg_runner.tell_parents_our_capabilities.\
                assert_called_with(self.ctxt)
        self.src_state_manager.get_our_capabilities.\
                assert_called_once()

    def test_update_capacities(self):
        self._setup_attrs('child-cell2', 'child-cell2!api-cell')
        capacs = 'fake_capacs'
        self.src_state_manager.get_our_capacities = mock.Mock()
        self.src_state_manager.get_our_capacities.return_value = capacs
        self.tgt_state_manager.update_cell_capacities = mock.Mock()
        self.tgt_msg_runner.tell_parents_our_capacities = mock.Mock()

        self.src_msg_runner.tell_parents_our_capacities(self.ctxt)
        self.tgt_state_manager.update_cell_capacities.\
                assert_called_with('child-cell2', capacs)
        self.tgt_msg_runner.tell_parents_our_capacities.\
                assert_called_with(self.ctxt)

    def test_announce_capabilities(self):
        self._setup_attrs('api-cell', 'api-cell!child-cell1')
        # To make this easier to test, make us only have 1 child cell.
        cell_state = self.src_state_manager.child_cells['child-cell1']
        self.src_state_manager.child_cells = {'child-cell1': cell_state}

        self.tgt_msg_runner.tell_parents_our_capabilities = mock.Mock()

        self.src_msg_runner.ask_children_for_capabilities(self.ctxt)
        self.tgt_msg_runner.tell_parents_our_capabilities.\
                assert_called_with(self.ctxt)

    def test_announce_capacities(self):
        self._setup_attrs('api-cell', 'api-cell!child-cell1')
        # To make this easier to test, make us only have 1 child cell.
        cell_state = self.src_state_manager.child_cells['child-cell1']
        self.src_state_manager.child_cells = {'child-cell1': cell_state}

        self.tgt_msg_runner.tell_parents_our_capacities = mock.Mock()

        self.src_msg_runner.ask_children_for_capacities(self.ctxt)
        self.tgt_msg_runner.tell_parents_our_capacities.\
                assert_called_with(self.ctxt)

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_service_get_by_compute_host(self, mock_cp_host):
        fake_host_name = 'fake-host-name'

        mock_cp_host.return_value = 'fake-service'

        response = self.src_msg_runner.service_get_by_compute_host(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name)
        result = response.value_or_raise()
        self.assertEqual('fake-service', result)
        mock_cp_host.assert_called_with(self.ctxt, fake_host_name)

    @mock.patch.object(objects.Service, 'get_by_args')
    @mock.patch.object(objects.Service, 'save')
    def test_service_update(self, mock_save, mock_get_args):
        binary = 'nova-compute'
        params_to_update = {'disabled': True, 'report_count': 13}

        fake_service = objects.Service(id=42, host='fake_host',
                                       binary='nova-compute',
                                       topic='compute')
        fake_service.compute_node = objects.ComputeNode(id=1, host='fake_host')
        mock_get_args.return_value = fake_service

        response = self.src_msg_runner.service_update(
                self.ctxt, self.tgt_cell_name,
                'fake_host', binary, params_to_update)
        result = response.value_or_raise()
        self.assertIsInstance(result, objects.Service)
        self.assertTrue(objects_base.obj_equal_prims(fake_service, result))
        mock_get_args.assert_called_with(self.ctxt,
                                         'fake_host', 'nova-compute')
        mock_save.assert_called_once()

    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_proxy_rpc_to_manager_call(self, mock_cp_host):
        fake_topic = 'fake-topic'
        fake_rpc_message = {'method': 'fake_rpc_method', 'args': {}}
        fake_host_name = 'fake-host-name'

        class FakeRPCClient(object):

            def prepare(self, timeout=5):
                return self

            def call(self, ctxt, method, **kwargs):
                return 'fake_result'

        def fake_get_client(target):
            return FakeRPCClient()

        # (Fixme) mock will mess up when mock an object of mock
        # how to mock a function of mock object's return value
        self.stub_out('nova.rpc.get_client', fake_get_client)

        response = self.src_msg_runner.proxy_rpc_to_manager(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name,
                fake_topic,
                fake_rpc_message, True, timeout=5)
        result = response.value_or_raise()
        self.assertEqual('fake_result', result)
        mock_cp_host.assert_called_with(self.ctxt, fake_host_name)

    @mock.patch.object(rpc, 'get_client')
    @mock.patch.object(objects.Service, 'get_by_compute_host')
    def test_proxy_rpc_to_manager_cast(self, mock_cp_host, mock_client):
        fake_topic = 'fake-topic'
        fake_rpc_message = {'method': 'fake_rpc_method', 'args': {}}
        fake_host_name = 'fake-host-name'
        target = oslo_messaging.Target(topic='fake-topic')

        rpcclient = mock.Mock()

        mock_client.return_value = rpcclient

        self.src_msg_runner.proxy_rpc_to_manager(
                self.ctxt,
                self.tgt_cell_name,
                fake_host_name,
                fake_topic,
                fake_rpc_message, False, timeout=None)
        mock_cp_host.assert_called_with(self.ctxt, fake_host_name)
        rpcclient.cast.assert_called_with(mock.ANY, 'fake_rpc_method')
        mock_client.assert_called_with(target)

    def test_task_log_get_all_targeted(self):
        task_name = 'fake_task_name'
        begin = 'fake_begin'
        end = 'fake_end'
        host = 'fake_host'
        state = 'fake_state'

        with mock.patch.object(self.tgt_db_inst, 'task_log_get_all') as log_a:
            log_a.return_value = ['fake_result']
            response = self.src_msg_runner.task_log_get_all(self.ctxt,
                    self.tgt_cell_name, task_name, begin, end, host=host,
                    state=state)
            log_a.assert_called_with(self.ctxt, task_name,
                    begin, end, host=host, state=state)
            self.assertIsInstance(response, list)
            self.assertEqual(1, len(response))
            result = response[0].value_or_raise()
            self.assertEqual(['fake_result'], result)

    @mock.patch.object(objects.ComputeNode, 'get_by_id')
    def test_compute_node_get(self, mock_get_id):
        compute_id = 'fake-id'
        mock_get_id.return_value = 'fake_result'

        response = self.src_msg_runner.compute_node_get(self.ctxt,
                self.tgt_cell_name, compute_id)
        result = response.value_or_raise()
        self.assertEqual('fake_result', result)
        mock_get_id.assert_called_with(self.ctxt, compute_id)

    @mock.patch.object(objects.ComputeNode, 'get_by_uuid',
                       return_value=objects.ComputeNode(uuid=uuids.cn_uuid))
    def test_compute_node_get_using_uuid(self, compute_node_get_by_uuid):
        """Tests that _TargetedMessageMethods.compute_node_get handles a
        UUID for the query parameter.
        """
        response = self.src_msg_runner.compute_node_get(
            self.ctxt, self.tgt_cell_name, uuids.cn_uuid)
        result = response.value_or_raise()
        self.assertEqual(uuids.cn_uuid, result.uuid)
        compute_node_get_by_uuid.assert_called_once_with(
            self.ctxt, uuids.cn_uuid)

    def test_actions_get(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_req_id = fake_server_actions.FAKE_REQUEST_ID1
        fake_act = fake_server_actions.FAKE_ACTIONS[fake_uuid][fake_req_id]

        with mock.patch.object(self.tgt_db_inst, 'actions_get') as ac_get:
            ac_get.return_value = [fake_act]

            response = self.src_msg_runner.actions_get(self.ctxt,
                                                   self.tgt_cell_name,
                                                   fake_uuid)
            result = response.value_or_raise()
            self.assertEqual([jsonutils.to_primitive(fake_act)], result)
            ac_get.assert_called_with(self.ctxt, fake_uuid)

    def test_action_get_by_request_id(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_req_id = fake_server_actions.FAKE_REQUEST_ID1
        fake_act = fake_server_actions.FAKE_ACTIONS[fake_uuid][fake_req_id]

        with mock.patch.object(self.tgt_db_inst,
                              'action_get_by_request_id') as act_id:
            act_id.return_value = fake_act

            response = self.src_msg_runner.action_get_by_request_id(self.ctxt,
                    self.tgt_cell_name, fake_uuid, 'req-fake')
            result = response.value_or_raise()
            self.assertEqual(jsonutils.to_primitive(fake_act), result)
            act_id.assert_called_with(self.ctxt, fake_uuid, 'req-fake')

    def test_action_events_get(self):
        fake_action_id = fake_server_actions.FAKE_ACTION_ID1
        fake_events = fake_server_actions.FAKE_EVENTS[fake_action_id]

        with mock.patch.object(self.tgt_db_inst,
                               'action_events_get') as act_get:
            act_get.return_value = fake_events

            response = self.src_msg_runner.action_events_get(self.ctxt,
                                                         self.tgt_cell_name,
                                                         'fake-action')
            result = response.value_or_raise()
            self.assertEqual(jsonutils.to_primitive(fake_events), result)
            act_get.assert_called_with(self.ctxt, 'fake-action')

    def test_validate_console_port(self):
        instance_uuid = uuids.instance
        instance = objects.Instance(uuid=instance_uuid)
        console_port = 'fake-port'
        console_type = 'fake-type'

        @mock.patch.object(objects.Instance, 'get_by_uuid',
                           return_value=instance)
        @mock.patch.object(self.tgt_c_rpcapi, 'validate_console_port',
                           return_value='fake_result')
        def do_test(mock_validate, mock_get):
            response = self.src_msg_runner.validate_console_port(self.ctxt,
                    self.tgt_cell_name, instance_uuid, console_port,
                    console_type)
            result = response.value_or_raise()
            self.assertEqual('fake_result', result)
            mock_get.assert_called_once_with(self.ctxt, instance_uuid)
            mock_validate.assert_called_once_with(self.ctxt, instance,
                                                  console_port, console_type)
        do_test()

    def test_get_migrations_for_a_given_cell(self):
        filters = {'cell_name': 'child-cell2', 'status': 'confirmed'}
        migrations_in_progress = [{'id': 123}]
        with mock.patch.object(self.tgt_compute_api,
                               'get_migrations') as get_mig:
            get_mig.return_value = migrations_in_progress

            responses = self.src_msg_runner.get_migrations(
                    self.ctxt,
                    self.tgt_cell_name, False, filters)
            result = responses[0].value_or_raise()
            self.assertEqual(migrations_in_progress, result)
            get_mig.assert_called_with(self.ctxt, filters)

    def test_get_migrations_for_an_invalid_cell(self):
        filters = {'cell_name': 'invalid_Cell', 'status': 'confirmed'}

        responses = self.src_msg_runner.get_migrations(
                self.ctxt,
                'api_cell!invalid_cell', False, filters)

        self.assertEqual(0, len(responses))

    def test_call_compute_api_with_obj(self):
        instance = objects.Instance()
        instance.uuid = uuids.fake
        self.mox.StubOutWithMock(instance, 'refresh')
        # Using 'snapshot' for this test, because it
        # takes args and kwargs.
        self.mox.StubOutWithMock(self.tgt_compute_api, 'snapshot')
        instance.refresh()
        self.tgt_compute_api.snapshot(
                self.ctxt, instance, 'name',
                extra_properties='props').AndReturn('foo')

        self.mox.ReplayAll()
        result = self.tgt_methods_cls._call_compute_api_with_obj(
                self.ctxt, instance, 'snapshot', 'name',
                extra_properties='props')
        self.assertEqual('foo', result)

    def test_call_compute_api_with_obj_no_cache(self):
        instance = objects.Instance()
        instance.uuid = uuids.fake
        error = exception.InstanceInfoCacheNotFound(
                                            instance_uuid=instance.uuid)
        with mock.patch.object(instance, 'refresh', side_effect=error):
            self.assertRaises(exception.InstanceInfoCacheNotFound,
                              self.tgt_methods_cls._call_compute_api_with_obj,
                              self.ctxt, instance, 'snapshot')

    def test_call_delete_compute_api_with_obj_no_cache(self):
        instance = objects.Instance()
        instance.uuid = uuids.fake
        error = exception.InstanceInfoCacheNotFound(
                                            instance_uuid=instance.uuid)
        with test.nested(
            mock.patch.object(instance, 'refresh',
                              side_effect=error),
            mock.patch.object(self.tgt_compute_api, 'delete')) as (inst,
                                                                   delete):
            self.tgt_methods_cls._call_compute_api_with_obj(self.ctxt,
                                                            instance,
                                                            'delete')
            delete.assert_called_once_with(self.ctxt, instance)

    def test_call_compute_with_obj_unknown_instance(self):
        instance = objects.Instance()
        instance.uuid = uuids.fake
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        self.mox.StubOutWithMock(instance, 'refresh')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_destroy_at_top')

        instance.refresh().AndRaise(
                exception.InstanceNotFound(instance_id=instance.uuid))

        self.tgt_msg_runner.instance_destroy_at_top(self.ctxt,
                                                    mox.IsA(objects.Instance))

        self.mox.ReplayAll()
        self.assertRaises(exception.InstanceNotFound,
                          self.tgt_methods_cls._call_compute_api_with_obj,
                          self.ctxt, instance, 'snapshot', 'name')

    def _instance_update_helper(self, admin_state_reset):
        class FakeMessage(object):
            pass

        message = FakeMessage()
        message.ctxt = self.ctxt

        instance = objects.Instance()
        instance.cell_name = self.tgt_cell_name
        instance.obj_reset_changes()
        instance.task_state = 'meow'
        instance.vm_state = 'wuff'
        instance.user_data = 'foo'
        instance.metadata = {'meta': 'data'}
        instance.system_metadata = {'system': 'metadata'}
        self.assertEqual(set(['user_data', 'vm_state', 'task_state',
                              'metadata', 'system_metadata']),
                         instance.obj_what_changed())

        self.mox.StubOutWithMock(instance, 'save')

        def _check_object(*args, **kwargs):
            # task_state and vm_state changes should have been cleared
            # before calling save()
            if admin_state_reset:
                self.assertEqual(
                        set(['user_data', 'vm_state', 'task_state']),
                        instance.obj_what_changed())
            else:
                self.assertEqual(set(['user_data']),
                                 instance.obj_what_changed())

        instance.save(expected_task_state='exp_task',
                      expected_vm_state='exp_vm').WithSideEffects(
                              _check_object)

        self.mox.ReplayAll()

        self.tgt_methods_cls.instance_update_from_api(
                message,
                instance,
                expected_vm_state='exp_vm',
                expected_task_state='exp_task',
                admin_state_reset=admin_state_reset)

    def test_instance_update_from_api(self):
        self._instance_update_helper(False)

    def test_instance_update_from_api_admin_state_reset(self):
        self._instance_update_helper(True)

    def test_instance_update_from_api_calls_skip_cells_sync(self):
        self.flags(enable=True, cell_type='compute', group='cells')
        instance = fake_instance.fake_instance_obj(self.ctxt)
        instance.cell_name = self.tgt_cell_name
        instance.task_state = 'meow'
        instance.vm_state = 'wuff'
        instance.user_data = 'foo'
        message = ''

        @mock.patch.object(instance, 'save', side_effect=test.TestingException)
        @mock.patch.object(instance, 'skip_cells_sync')
        def _ensure_skip_cells_sync_called(mock_sync, mock_save):
            self.assertRaises(test.TestingException,
                    self.tgt_methods_cls.instance_update_from_api,
                    message, instance, expected_vm_state='exp_vm',
                    expected_task_state='exp_task', admin_state_reset=False)
            mock_sync.assert_has_calls([mock.call()])

        _ensure_skip_cells_sync_called()
        self.assertEqual(self.tgt_cell_name, instance.cell_name)

    @mock.patch.object(db, 'instance_update_and_get_original')
    def test_instance_update_from_api_skips_cell_sync(self, mock_db_update):
        self.flags(enable=True, cell_type='compute', group='cells')
        instance = fake_instance.fake_instance_obj(self.ctxt)
        instance.cell_name = self.tgt_cell_name
        instance.task_state = 'meow'
        instance.vm_state = 'wuff'
        instance.user_data = 'foo'
        message = ''

        inst_ref = dict(objects_base.obj_to_primitive(instance))
        mock_db_update.return_value = (inst_ref, inst_ref)

        with mock.patch.object(cells_rpcapi.CellsAPI,
                'instance_update_at_top') as inst_upd_at_top:
            self.tgt_methods_cls.instance_update_from_api(message, instance,
                    expected_vm_state='exp_vm', expected_task_state='exp_task',
                    admin_state_reset=False)
            self.assertEqual(0, inst_upd_at_top.call_count)

    def _test_instance_action_method(self, method, args, kwargs,
                                     expected_args, expected_kwargs,
                                     expect_result):
        class FakeMessage(object):
            pass

        message = FakeMessage()
        message.ctxt = self.ctxt
        message.need_response = expect_result

        meth_cls = self.tgt_methods_cls
        self.mox.StubOutWithMock(meth_cls, '_call_compute_api_with_obj')

        method_corrections = {
            'terminate': 'delete',
            }
        api_method = method_corrections.get(method, method)

        meth_cls._call_compute_api_with_obj(
                self.ctxt, 'fake-instance', api_method,
                *expected_args, **expected_kwargs).AndReturn('meow')

        self.mox.ReplayAll()

        method_translations = {'revert_resize': 'revert_resize',
                               'confirm_resize': 'confirm_resize',
                               'reset_network': 'reset_network',
                               'inject_network_info': 'inject_network_info',
                               'set_admin_password': 'set_admin_password',
                              }
        tgt_method = method_translations.get(method,
                                             '%s_instance' % method)
        result = getattr(meth_cls, tgt_method)(
                message, 'fake-instance', *args, **kwargs)
        if expect_result:
            self.assertEqual('meow', result)

    def test_start_instance(self):
        self._test_instance_action_method('start', (), {}, (), {}, False)

    def test_stop_instance_cast(self):
        self._test_instance_action_method('stop', (), {}, (),
                                          {'do_cast': True,
                                           'clean_shutdown': True}, False)

    def test_stop_instance_call(self):
        self._test_instance_action_method('stop', (), {}, (),
                                          {'do_cast': False,
                                           'clean_shutdown': True}, True)

    def test_reboot_instance(self):
        kwargs = dict(reboot_type='HARD')
        self._test_instance_action_method('reboot', (), kwargs, (),
                                          kwargs, False)

    def test_suspend_instance(self):
        self._test_instance_action_method('suspend', (), {}, (), {}, False)

    def test_resume_instance(self):
        self._test_instance_action_method('resume', (), {}, (), {}, False)

    def test_get_host_uptime(self):
        host_name = "fake-host"
        host_uptime = (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                       " 0.20, 0.12, 0.14")
        self.mox.StubOutWithMock(self.tgt_host_api, 'get_host_uptime')
        self.tgt_host_api.get_host_uptime(self.ctxt, host_name).\
            AndReturn(host_uptime)
        self.mox.ReplayAll()
        response = self.src_msg_runner.get_host_uptime(self.ctxt,
                                                       self.tgt_cell_name,
                                                       host_name)
        expected_host_uptime = response.value_or_raise()
        self.assertEqual(host_uptime, expected_host_uptime)

    def test_terminate_instance(self):
        self._test_instance_action_method('terminate',
                                          (), {}, (), {}, False)

    def test_soft_delete_instance(self):
        self._test_instance_action_method('soft_delete',
                                          (), {}, (), {}, False)

    def test_pause_instance(self):
        self._test_instance_action_method('pause', (), {}, (), {}, False)

    def test_unpause_instance(self):
        self._test_instance_action_method('unpause', (), {}, (), {}, False)

    def _test_resize_instance(self, clean_shutdown=True):
        kwargs = dict(flavor=dict(id=42, flavorid='orangemocchafrappuccino'),
                      extra_instance_updates=dict(cow='moo'),
                      clean_shutdown=clean_shutdown)
        expected_kwargs = dict(flavor_id='orangemocchafrappuccino', cow='moo',
                               clean_shutdown=clean_shutdown)
        self._test_instance_action_method('resize', (), kwargs,
                                          (), expected_kwargs,
                                          False)

    def test_resize_instance(self):
        self._test_resize_instance()

    def test_resize_instance_forced_shutdown(self):
        self._test_resize_instance(clean_shutdown=False)

    def test_live_migrate_instance(self):
        kwargs = dict(block_migration='fake-block-mig',
                      disk_over_commit='fake-commit',
                      host_name='fake-host')
        expected_args = ('fake-block-mig', 'fake-commit', 'fake-host')
        self._test_instance_action_method('live_migrate', (), kwargs,
                                          expected_args, {}, False)

    def test_revert_resize(self):
        self._test_instance_action_method('revert_resize',
                                          (), {}, (), {}, False)

    def test_confirm_resize(self):
        self._test_instance_action_method('confirm_resize',
                                          (), {}, (), {}, False)

    def test_reset_network(self):
        self._test_instance_action_method('reset_network',
                                          (), {}, (), {}, False)

    def test_inject_network_info(self):
        self._test_instance_action_method('inject_network_info',
                                          (), {}, (), {}, False)

    def test_snapshot_instance(self):
        inst = objects.Instance()
        meth_cls = self.tgt_methods_cls

        self.mox.StubOutWithMock(inst, 'refresh')
        self.mox.StubOutWithMock(inst, 'save')
        self.mox.StubOutWithMock(meth_cls.compute_rpcapi, 'snapshot_instance')

        def check_state(expected_task_state=None):
            self.assertEqual(task_states.IMAGE_SNAPSHOT_PENDING,
                             inst.task_state)

        inst.refresh()
        inst.save(expected_task_state=[None]).WithSideEffects(check_state)

        meth_cls.compute_rpcapi.snapshot_instance(self.ctxt,
                                                  inst, 'image-id')

        self.mox.ReplayAll()

        class FakeMessage(object):
            pass

        message = FakeMessage()
        message.ctxt = self.ctxt
        message.need_response = False

        meth_cls.snapshot_instance(message, inst, image_id='image-id')

    def test_backup_instance(self):
        inst = objects.Instance()
        meth_cls = self.tgt_methods_cls

        self.mox.StubOutWithMock(inst, 'refresh')
        self.mox.StubOutWithMock(inst, 'save')
        self.mox.StubOutWithMock(meth_cls.compute_rpcapi, 'backup_instance')

        def check_state(expected_task_state=None):
            self.assertEqual(task_states.IMAGE_BACKUP, inst.task_state)

        inst.refresh()
        inst.save(expected_task_state=[None]).WithSideEffects(check_state)

        meth_cls.compute_rpcapi.backup_instance(self.ctxt,
                                                inst,
                                                'image-id',
                                                'backup-type',
                                                'rotation')

        self.mox.ReplayAll()

        class FakeMessage(object):
            pass

        message = FakeMessage()
        message.ctxt = self.ctxt
        message.need_response = False

        meth_cls.backup_instance(message, inst,
                                 image_id='image-id',
                                 backup_type='backup-type',
                                 rotation='rotation')

    def test_set_admin_password(self):
        args = ['fake-password']
        self._test_instance_action_method('set_admin_password', args, {}, args,
                {}, False)


class CellsBroadcastMethodsTestCase(test.NoDBTestCase):
    """Test case for _BroadcastMessageMethods class.  Most of these
    tests actually test the full path from the MessageRunner through
    to the functionality of the message method.  Hits 2 birds with 1
    stone, even though it's a little more than a unit test.
    """

    def setUp(self):
        super(CellsBroadcastMethodsTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self._setup_attrs()

    def _setup_attrs(self, up=True):
        mid_cell = 'child-cell2'
        if up:
            src_cell = 'grandchild-cell1'
            tgt_cell = 'api-cell'
        else:
            src_cell = 'api-cell'
            tgt_cell = 'grandchild-cell1'

        self.src_msg_runner = fakes.get_message_runner(src_cell)
        methods_cls = self.src_msg_runner.methods_by_type['broadcast']
        self.src_methods_cls = methods_cls
        self.src_db_inst = methods_cls.db
        self.src_compute_api = methods_cls.compute_api
        self.src_ca_rpcapi = methods_cls.consoleauth_rpcapi

        if not up:
            # fudge things so we only have 1 child to broadcast to
            state_manager = self.src_msg_runner.state_manager
            for cell in state_manager.get_child_cells():
                if cell.name != 'child-cell2':
                    del state_manager.child_cells[cell.name]

        self.mid_msg_runner = fakes.get_message_runner(mid_cell)
        methods_cls = self.mid_msg_runner.methods_by_type['broadcast']
        self.mid_methods_cls = methods_cls
        self.mid_db_inst = methods_cls.db
        self.mid_compute_api = methods_cls.compute_api
        self.mid_ca_rpcapi = methods_cls.consoleauth_rpcapi

        self.tgt_msg_runner = fakes.get_message_runner(tgt_cell)
        methods_cls = self.tgt_msg_runner.methods_by_type['broadcast']
        self.tgt_methods_cls = methods_cls
        self.tgt_db_inst = methods_cls.db
        self.tgt_compute_api = methods_cls.compute_api
        self.tgt_ca_rpcapi = methods_cls.consoleauth_rpcapi

    def test_at_the_top(self):
        self.assertTrue(self.tgt_methods_cls._at_the_top())
        self.assertFalse(self.mid_methods_cls._at_the_top())
        self.assertFalse(self.src_methods_cls._at_the_top())

    def test_apply_expected_states_building(self):
        instance_info = objects.Instance(vm_state=vm_states.BUILDING)
        expected = instance_info.obj_clone()
        expected.expected_vm_state = [vm_states.BUILDING, None]
        expected_vm_state = self.src_methods_cls._get_expected_vm_state(
                                instance_info)
        self.assertEqual(expected.expected_vm_state, expected_vm_state)

    def test_apply_expected_states_resize_finish(self):
        instance_info = objects.Instance(task_state=task_states.RESIZE_FINISH)
        exp_states = [task_states.RESIZE_FINISH,
                      task_states.RESIZE_MIGRATED,
                      task_states.RESIZE_MIGRATING,
                      task_states.RESIZE_PREP]
        expected = instance_info.obj_clone()
        expected.expected_task_state = exp_states
        expected_task_state = self.src_methods_cls._get_expected_task_state(
                                  instance_info)
        self.assertEqual(expected.expected_task_state, expected_task_state)

    def _test_instance_update_at_top(self, exists=True):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_info_cache = objects.InstanceInfoCache(
            instance_uuid=fake_uuid)
        fake_sys_metadata = {'key1': 'value1',
                             'key2': 'value2'}
        fake_attrs = {'uuid': fake_uuid,
                      'cell_name': 'fake',
                      'info_cache': fake_info_cache,
                      'system_metadata': fake_sys_metadata}
        fake_instance = objects.Instance(**fake_attrs)
        expected_cell_name = 'api-cell!child-cell2!grandchild-cell1'

        def fake_save(instance):
            self.assertEqual(fake_uuid, instance.uuid)
            self.assertEqual(expected_cell_name, instance.cell_name)
            self.assertEqual(fake_info_cache, instance.info_cache)
            self.assertEqual(fake_sys_metadata, instance.system_metadata)

        @mock.patch.object(objects.Instance, 'save')
        @mock.patch.object(objects.Instance, 'create')
        def do_test(mock_create, mock_save):
            if exists:
                mock_save.side_effect = fake_save
            else:
                error = exception.InstanceNotFound(instance_id=fake_uuid)
                mock_save.side_effect = error

            self.src_msg_runner.instance_update_at_top(self.ctxt,
                                                       fake_instance)
            if exists:
                mock_save.assert_called_once_with(expected_vm_state=None,
                                                  expected_task_state=None)
                self.assertFalse(mock_create.called)
            else:
                mock_save.assert_called_once_with(expected_vm_state=None,
                                                  expected_task_state=None)
                mock_create.assert_called_once_with()
        do_test()

    def test_instance_update_at_top(self):
        self._test_instance_update_at_top()

    def test_instance_update_at_top_does_not_already_exist(self):
        self._test_instance_update_at_top(exists=False)

    def test_instance_update_at_top_with_building_state(self):
        fake_uuid = fake_server_actions.FAKE_UUID
        fake_info_cache = objects.InstanceInfoCache(
            instance_uuid=fake_uuid)
        fake_sys_metadata = {'key1': 'value1',
                             'key2': 'value2'}
        fake_attrs = {'uuid': fake_uuid,
                      'cell_name': 'fake',
                      'info_cache': fake_info_cache,
                      'system_metadata': fake_sys_metadata,
                      'vm_state': vm_states.BUILDING}
        fake_instance = objects.Instance(**fake_attrs)
        expected_cell_name = 'api-cell!child-cell2!grandchild-cell1'
        expected_vm_state = [vm_states.BUILDING, None]

        def fake_save(instance):
            self.assertEqual(fake_uuid, instance.uuid)
            self.assertEqual(expected_cell_name, instance.cell_name)
            self.assertEqual(fake_info_cache, instance.info_cache)
            self.assertEqual(fake_sys_metadata, instance.system_metadata)

        with mock.patch.object(objects.Instance, 'save',
                               side_effect=fake_save) as mock_save:
            self.src_msg_runner.instance_update_at_top(self.ctxt,
                                                       fake_instance)
            # Check that save is called with the right expected states.
            mock_save.assert_called_once_with(
                expected_vm_state=expected_vm_state, expected_task_state=None)

    def test_instance_destroy_at_top(self):
        fake_instance = objects.Instance(uuid=uuids.instance)

        with mock.patch.object(objects.Instance, 'destroy') as mock_destroy:
            self.src_msg_runner.instance_destroy_at_top(self.ctxt,
                                                        fake_instance)
            mock_destroy.assert_called_once_with()

    def test_instance_destroy_at_top_incomplete_instance_obj(self):
        fake_instance = objects.Instance(uuid=uuids.instance)
        with mock.patch.object(objects.Instance, 'get_by_uuid') as mock_get:
            self.src_msg_runner.instance_destroy_at_top(self.ctxt,
                    fake_instance)
            mock_get.assert_called_once_with(self.ctxt, fake_instance.uuid)

    def test_instance_hard_delete_everywhere(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        instance = {'uuid': 'meow'}

        # Should not be called in src (API cell)
        self.mox.StubOutWithMock(self.src_compute_api, 'delete')

        self.mox.StubOutWithMock(self.mid_compute_api, 'delete')
        self.mox.StubOutWithMock(self.tgt_compute_api, 'delete')

        self.mid_compute_api.delete(self.ctxt, instance)
        self.tgt_compute_api.delete(self.ctxt, instance)

        self.mox.ReplayAll()

        self.src_msg_runner.instance_delete_everywhere(self.ctxt,
                instance, 'hard')

    def test_instance_soft_delete_everywhere(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        instance = {'uuid': 'meow'}

        # Should not be called in src (API cell)
        self.mox.StubOutWithMock(self.src_compute_api, 'soft_delete')

        self.mox.StubOutWithMock(self.mid_compute_api, 'soft_delete')
        self.mox.StubOutWithMock(self.tgt_compute_api, 'soft_delete')

        self.mid_compute_api.soft_delete(self.ctxt, instance)
        self.tgt_compute_api.soft_delete(self.ctxt, instance)

        self.mox.ReplayAll()

        self.src_msg_runner.instance_delete_everywhere(self.ctxt,
                instance, 'soft')

    def test_instance_fault_create_at_top(self):
        fake_instance_fault = {'id': 1,
                               'message': 'fake-message',
                               'details': 'fake-details'}

        if_mock = mock.Mock(spec_set=objects.InstanceFault)

        def _check_create():
            self.assertEqual('fake-message', if_mock.message)
            self.assertEqual('fake-details', if_mock.details)
            # Should not be set
            self.assertNotEqual(1, if_mock.id)

        if_mock.create.side_effect = _check_create

        with mock.patch.object(objects, 'InstanceFault') as if_obj_mock:
            if_obj_mock.return_value = if_mock
            self.src_msg_runner.instance_fault_create_at_top(
                    self.ctxt, fake_instance_fault)

        if_obj_mock.assert_called_once_with(context=self.ctxt)
        if_mock.create.assert_called_once_with()

    def test_bw_usage_update_at_top(self):
        fake_bw_update_info = {'uuid': 'fake_uuid',
                               'mac': 'fake_mac',
                               'start_period': 'fake_start_period',
                               'bw_in': 'fake_bw_in',
                               'bw_out': 'fake_bw_out',
                               'last_ctr_in': 'fake_last_ctr_in',
                               'last_ctr_out': 'fake_last_ctr_out',
                               'last_refreshed': 'fake_last_refreshed'}

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst, 'bw_usage_update')
        self.mox.StubOutWithMock(self.mid_db_inst, 'bw_usage_update')

        self.mox.StubOutWithMock(self.tgt_db_inst, 'bw_usage_update')
        self.tgt_db_inst.bw_usage_update(self.ctxt, **fake_bw_update_info)

        self.mox.ReplayAll()

        self.src_msg_runner.bw_usage_update_at_top(self.ctxt,
                                                   fake_bw_update_info)

    def test_sync_instances(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        project_id = 'fake_project_id'
        updated_since_raw = 'fake_updated_since_raw'
        updated_since_parsed = 'fake_updated_since_parsed'
        deleted = 'fake_deleted'

        instance1 = objects.Instance(uuid=uuids.instance_1, deleted=False)
        instance2 = objects.Instance(uuid=uuids.instance_2, deleted=True)
        fake_instances = [instance1, instance2]

        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_update_at_top')
        self.mox.StubOutWithMock(self.tgt_msg_runner,
                                 'instance_destroy_at_top')

        self.mox.StubOutWithMock(timeutils, 'parse_isotime')
        self.mox.StubOutWithMock(cells_utils, 'get_instances_to_sync')

        # Middle cell.
        timeutils.parse_isotime(updated_since_raw).AndReturn(
                updated_since_parsed)
        cells_utils.get_instances_to_sync(self.ctxt,
                updated_since=updated_since_parsed,
                project_id=project_id,
                deleted=deleted).AndReturn([])

        # Bottom/Target cell
        timeutils.parse_isotime(updated_since_raw).AndReturn(
                updated_since_parsed)
        cells_utils.get_instances_to_sync(self.ctxt,
                updated_since=updated_since_parsed,
                project_id=project_id,
                deleted=deleted).AndReturn(fake_instances)
        self.tgt_msg_runner.instance_update_at_top(self.ctxt, instance1)
        self.tgt_msg_runner.instance_destroy_at_top(self.ctxt, instance2)

        self.mox.ReplayAll()

        self.src_msg_runner.sync_instances(self.ctxt,
                project_id, updated_since_raw, deleted)

    def test_service_get_all_with_disabled(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(objects.ServiceList, 'get_all')

        # Calls are made from grandchild-cell to api-cell
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=None).AndReturn([4, 5])
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=None).AndReturn([3])
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=None).AndReturn([1, 2])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.service_get_all(ctxt,
                                                        filters={})
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_service_get_all_without_disabled(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        disabled = False
        filters = {'disabled': disabled}

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(objects.ServiceList, 'get_all')

        # Calls are made from grandchild-cell to api-cell
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=disabled).AndReturn([4, 5])
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=disabled).AndReturn([3])
        objects.ServiceList.get_all(
            mox.IgnoreArg(), disabled=disabled).AndReturn([1, 2])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.service_get_all(ctxt,
                                                        filters=filters)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_task_log_get_all_broadcast(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        task_name = 'fake_task_name'
        begin = 'fake_begin'
        end = 'fake_end'
        host = 'fake_host'
        state = 'fake_state'

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst, 'task_log_get_all')
        self.mox.StubOutWithMock(self.mid_db_inst, 'task_log_get_all')
        self.mox.StubOutWithMock(self.tgt_db_inst, 'task_log_get_all')

        self.src_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([1, 2])
        self.mid_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([3])
        self.tgt_db_inst.task_log_get_all(ctxt, task_name,
                begin, end, host=host, state=state).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.task_log_get_all(ctxt, None,
                task_name, begin, end, host=host, state=state)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_get_all(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_all')

        # Calls are made from grandchild-cell to api-cell
        objects.ComputeNodeList.get_all(mox.IgnoreArg()).AndReturn([4, 5])
        objects.ComputeNodeList.get_all(mox.IgnoreArg()).AndReturn([3])
        objects.ComputeNodeList.get_all(mox.IgnoreArg()).AndReturn([1, 2])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_get_all(ctxt)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_get_all_with_hyp_match(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)
        hypervisor_match = 'meow'

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(objects.ComputeNodeList, 'get_by_hypervisor')

        # Calls are made from grandchild-cell to api-cell
        objects.ComputeNodeList.get_by_hypervisor(
            ctxt, hypervisor_match).AndReturn([4, 5])
        objects.ComputeNodeList.get_by_hypervisor(
            ctxt, hypervisor_match).AndReturn([3])
        objects.ComputeNodeList.get_by_hypervisor(
            ctxt, hypervisor_match).AndReturn([1, 2])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_get_all(ctxt,
                hypervisor_match=hypervisor_match)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_compute_node_stats(self):
        # Reset this, as this is a broadcast down.
        self._setup_attrs(up=False)

        ctxt = self.ctxt.elevated()

        self.mox.StubOutWithMock(self.src_db_inst,
                                 'compute_node_statistics')
        self.mox.StubOutWithMock(self.mid_db_inst,
                                 'compute_node_statistics')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                                 'compute_node_statistics')

        self.src_db_inst.compute_node_statistics(ctxt).AndReturn([1, 2])
        self.mid_db_inst.compute_node_statistics(ctxt).AndReturn([3])
        self.tgt_db_inst.compute_node_statistics(ctxt).AndReturn([4, 5])

        self.mox.ReplayAll()

        responses = self.src_msg_runner.compute_node_stats(ctxt)
        response_values = [(resp.cell_name, resp.value_or_raise())
                           for resp in responses]
        expected = [('api-cell!child-cell2!grandchild-cell1', [4, 5]),
                    ('api-cell!child-cell2', [3]),
                    ('api-cell', [1, 2])]
        self.assertEqual(expected, response_values)

    def test_consoleauth_delete_tokens(self):
        fake_uuid = 'fake-instance-uuid'

        # To show these should not be called in src/mid-level cell
        self.mox.StubOutWithMock(self.src_ca_rpcapi,
                                 'delete_tokens_for_instance')
        self.mox.StubOutWithMock(self.mid_ca_rpcapi,
                                 'delete_tokens_for_instance')

        self.mox.StubOutWithMock(self.tgt_ca_rpcapi,
                                 'delete_tokens_for_instance')
        self.tgt_ca_rpcapi.delete_tokens_for_instance(self.ctxt, fake_uuid)

        self.mox.ReplayAll()

        self.src_msg_runner.consoleauth_delete_tokens(self.ctxt, fake_uuid)

    def test_bdm_update_or_create_with_none_create(self):
        fake_bdm = {'id': 'fake_id',
                    'volume_id': 'fake_volume_id'}
        expected_bdm = fake_bdm.copy()
        expected_bdm.pop('id')

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_update_or_create')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_update_or_create')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_update_or_create')
        self.tgt_db_inst.block_device_mapping_update_or_create(
                self.ctxt, expected_bdm, legacy=False)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_update_or_create_at_top(self.ctxt,
                                                        fake_bdm,
                                                        create=None)

    def test_bdm_update_or_create_with_true_create(self):
        fake_bdm = {'id': 'fake_id',
                    'volume_id': 'fake_volume_id'}
        expected_bdm = fake_bdm.copy()
        expected_bdm.pop('id')

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_create')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_create')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_create')
        self.tgt_db_inst.block_device_mapping_create(
                self.ctxt, fake_bdm, legacy=False)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_update_or_create_at_top(self.ctxt,
                                                        fake_bdm,
                                                        create=True)

    def test_bdm_update_or_create_with_false_create_vol_id(self):
        fake_bdm = {'id': 'fake_id',
                    'instance_uuid': uuids.instance,
                    'device_name': 'fake_device_name',
                    'volume_id': 'fake_volume_id'}
        expected_bdm = fake_bdm.copy()
        expected_bdm.pop('id')

        fake_inst_bdms = [{'id': 1,
                           'volume_id': 'not-a-match',
                           'device_name': 'not-a-match'},
                          {'id': 2,
                           'volume_id': 'fake_volume_id',
                           'device_name': 'not-a-match'},
                          {'id': 3,
                           'volume_id': 'not-a-match',
                           'device_name': 'not-a-match'}]

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_update')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_update')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_update')

        self.tgt_db_inst.block_device_mapping_get_all_by_instance(
                self.ctxt, uuids.instance).AndReturn(
                        fake_inst_bdms)
        # Should try to update ID 2.
        self.tgt_db_inst.block_device_mapping_update(
                self.ctxt, 2, expected_bdm, legacy=False)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_update_or_create_at_top(self.ctxt,
                                                        fake_bdm,
                                                        create=False)

    def test_bdm_update_or_create_with_false_create_dev_name(self):
        fake_bdm = {'id': 'fake_id',
                    'instance_uuid': uuids.instance,
                    'device_name': 'fake_device_name',
                    'volume_id': 'fake_volume_id'}
        expected_bdm = fake_bdm.copy()
        expected_bdm.pop('id')

        fake_inst_bdms = [{'id': 1,
                           'volume_id': 'not-a-match',
                           'device_name': 'not-a-match'},
                          {'id': 2,
                           'volume_id': 'not-a-match',
                           'device_name': 'fake_device_name'},
                          {'id': 3,
                           'volume_id': 'not-a-match',
                           'device_name': 'not-a-match'}]

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_update')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_update')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_get_all_by_instance')
        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_update')

        self.tgt_db_inst.block_device_mapping_get_all_by_instance(
                self.ctxt, uuids.instance).AndReturn(
                        fake_inst_bdms)
        # Should try to update ID 2.
        self.tgt_db_inst.block_device_mapping_update(
                self.ctxt, 2, expected_bdm, legacy=False)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_update_or_create_at_top(self.ctxt,
                                                        fake_bdm,
                                                        create=False)

    def test_bdm_destroy_by_volume(self):
        fake_instance_uuid = uuids.instance
        fake_volume_id = 'fake-volume-name'

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_destroy_by_instance_and_volume')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_destroy_by_instance_and_volume')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_destroy_by_instance_and_volume')
        self.tgt_db_inst.block_device_mapping_destroy_by_instance_and_volume(
                self.ctxt, fake_instance_uuid, fake_volume_id)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_destroy_at_top(self.ctxt, fake_instance_uuid,
                                               volume_id=fake_volume_id)

    def test_bdm_destroy_by_device(self):
        fake_instance_uuid = uuids.instance
        fake_device_name = 'fake-device-name'

        # Shouldn't be called for these 2 cells
        self.mox.StubOutWithMock(self.src_db_inst,
                'block_device_mapping_destroy_by_instance_and_device')
        self.mox.StubOutWithMock(self.mid_db_inst,
                'block_device_mapping_destroy_by_instance_and_device')

        self.mox.StubOutWithMock(self.tgt_db_inst,
                'block_device_mapping_destroy_by_instance_and_device')
        self.tgt_db_inst.block_device_mapping_destroy_by_instance_and_device(
                self.ctxt, fake_instance_uuid, fake_device_name)

        self.mox.ReplayAll()

        self.src_msg_runner.bdm_destroy_at_top(self.ctxt, fake_instance_uuid,
                                               device_name=fake_device_name)

    def test_get_migrations(self):
        self._setup_attrs(up=False)
        filters = {'status': 'confirmed'}
        migrations_from_cell1 = [{'id': 123}]
        migrations_from_cell2 = [{'id': 456}]
        self.mox.StubOutWithMock(self.mid_compute_api,
                                 'get_migrations')

        self.mid_compute_api.get_migrations(self.ctxt, filters).\
            AndReturn(migrations_from_cell1)

        self.mox.StubOutWithMock(self.tgt_compute_api,
                                 'get_migrations')

        self.tgt_compute_api.get_migrations(self.ctxt, filters).\
            AndReturn(migrations_from_cell2)

        self.mox.ReplayAll()

        responses = self.src_msg_runner.get_migrations(
                self.ctxt,
                None, False, filters)
        self.assertEqual(2, len(responses))
        for response in responses:
            self.assertIn(response.value_or_raise(), [migrations_from_cell1,
                                                      migrations_from_cell2])

    @mock.patch.object(objects.KeyPair, 'get_by_name',
                       return_value='fake_keypair')
    def test_get_keypair_at_top(self, fake_get_by_name):
        user_id = 'fake_user_id'
        name = 'fake_keypair_name'
        responses = self.src_msg_runner.get_keypair_at_top(self.ctxt,
                                                           user_id, name)
        fake_get_by_name.assert_called_once_with(self.ctxt, user_id, name)

        for response in responses:
            if response.value is not None:
                self.assertEqual('fake_keypair', response.value)

    @mock.patch.object(objects.KeyPair, 'get_by_name')
    def test_get_keypair_at_top_with_objects_exception(self, fake_get_by_name):
        user_id = 'fake_user_id'
        name = 'fake_keypair_name'
        keypair_exception = exception.KeypairNotFound(user_id=user_id,
                                                      name=name)
        fake_get_by_name.side_effect = keypair_exception
        responses = self.src_msg_runner.get_keypair_at_top(self.ctxt,
                                                           user_id,
                                                           name)
        fake_get_by_name.assert_called_once_with(self.ctxt, user_id, name)

        for response in responses:
            self.assertIsNone(response.value)

    @mock.patch.object(messaging._BroadcastMessage, 'process')
    def test_get_keypair_at_top_with_process_response(self, fake_process):
        user_id = 'fake_user_id'
        name = 'fake_keypair_name'
        response = messaging.Response(self.ctxt, 'cell', 'keypair', False)
        other_response = messaging.Response(self.ctxt, 'cell',
                                            'fake_other_keypair', False)
        fake_process.return_value = [response, other_response]

        responses = self.src_msg_runner.get_keypair_at_top(self.ctxt,
                                                           user_id, name)
        fake_process.assert_called_once_with()
        self.assertEqual(fake_process.return_value, responses)


class CellsPublicInterfacesTestCase(test.NoDBTestCase):
    """Test case for the public interfaces into cells messaging."""
    def setUp(self):
        super(CellsPublicInterfacesTestCase, self).setUp()
        fakes.init(self)
        self.ctxt = context.RequestContext('fake', 'fake')
        self.our_name = 'api-cell'
        self.msg_runner = fakes.get_message_runner(self.our_name)
        self.state_manager = self.msg_runner.state_manager

    @mock.patch.object(messaging, '_TargetedMessage')
    def test_resize_instance(self, mock_message):
        instance = objects.Instance(cell_name='api-cell!child-cell')
        flavor = 'fake'
        extra_instance_updates = {'fake': 'fake'}
        clean_shutdown = True
        self.msg_runner.resize_instance(self.ctxt, instance, flavor,
                                        extra_instance_updates,
                                        clean_shutdown=clean_shutdown)
        extra_kwargs = dict(flavor=flavor,
                            extra_instance_updates=extra_instance_updates,
                            clean_shutdown=clean_shutdown)
        method_kwargs = {'instance': instance}
        method_kwargs.update(extra_kwargs)
        mock_message.assert_called_once_with(self.msg_runner, self.ctxt,
                                             'resize_instance',
                                             method_kwargs, 'down',
                                             instance.cell_name,
                                             need_response=False)
