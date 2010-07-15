# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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

import logging
import time

from xml.etree import ElementTree

from nova import vendor
from twisted.internet import defer

from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.compute import model
from nova.compute import node

FLAGS = flags.FLAGS


class InstanceXmlTestCase(test.TrialTestCase):
    # @defer.inlineCallbacks
    def test_serialization(self):
        # TODO: Reimplement this, it doesn't make sense in redis-land
        return

        # instance_id = 'foo'
        # first_node = node.Node()
        # inst = yield first_node.run_instance(instance_id)
        #
        # # force the state so that we can verify that it changes
        # inst._s['state'] = node.Instance.NOSTATE
        # xml = inst.toXml()
        # self.assert_(ElementTree.parse(StringIO.StringIO(xml)))
        #
        # second_node = node.Node()
        # new_inst = node.Instance.fromXml(second_node._conn, pool=second_node._pool, xml=xml)
        # self.assertEqual(new_inst.state, node.Instance.RUNNING)
        # rv = yield first_node.terminate_instance(instance_id)


class NodeConnectionTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(NodeConnectionTestCase, self).setUp()
        self.flags(fake_libvirt=True,
                   fake_storage=True,
                   fake_users=True)
        self.node = node.Node()

    def create_instance(self):
        instdir = model.InstanceDirectory()
        inst = instdir.new()
        # TODO(ja): add ami, ari, aki, user_data
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type'] = 'm1.tiny'
        inst['node_name'] = FLAGS.node_name
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        inst.save()
        return inst['instance_id']

    @defer.inlineCallbacks
    def test_run_describe_terminate(self):
        instance_id = self.create_instance()

        rv = yield self.node.run_instance(instance_id)

        rv = yield self.node.describe_instances()
        logging.info("Running instances: %s", rv)
        self.assertEqual(rv[instance_id].name, instance_id)

        rv = yield self.node.terminate_instance(instance_id)

        rv = yield self.node.describe_instances()
        logging.info("After terminating instances: %s", rv)
        self.assertEqual(rv, {})

    @defer.inlineCallbacks
    def test_reboot(self):
        instance_id = self.create_instance()
        rv = yield self.node.run_instance(instance_id)

        rv = yield self.node.describe_instances()
        self.assertEqual(rv[instance_id].name, instance_id)

        yield self.node.reboot_instance(instance_id)

        rv = yield self.node.describe_instances()
        self.assertEqual(rv[instance_id].name, instance_id)
        rv = yield self.node.terminate_instance(instance_id)

    @defer.inlineCallbacks
    def test_console_output(self):
        instance_id = self.create_instance()
        rv = yield self.node.run_instance(instance_id)

        console = yield self.node.get_console_output(instance_id)
        self.assert_(console)
        rv = yield self.node.terminate_instance(instance_id)

    @defer.inlineCallbacks
    def test_run_instance_existing(self):
        instance_id = self.create_instance()
        rv = yield self.node.run_instance(instance_id)

        rv = yield self.node.describe_instances()
        self.assertEqual(rv[instance_id].name, instance_id)

        self.assertRaises(exception.Error, self.node.run_instance, instance_id)
        rv = yield self.node.terminate_instance(instance_id)
