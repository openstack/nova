# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

import logging
import time
from twisted.internet import defer
from xml.etree import ElementTree

from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.auth import manager
from nova.compute import service


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


class ComputeConnectionTestCase(test.TrialTestCase):
    def setUp(self):
        logging.getLogger().setLevel(logging.DEBUG)
        super(ComputeConnectionTestCase, self).setUp()
        self.flags(connection_type='fake',
                   fake_storage=True)
        self.compute = service.ComputeService()
        self.manager = manager.AuthManager()
        user = self.manager.create_user('fake', 'fake', 'fake')
        project = self.manager.create_project('fake', 'fake', 'fake')

    def tearDown(self):
        self.manager.delete_user('fake')
        self.manager.delete_project('fake')

    def _create_instance(self):
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = 'fake'
        inst['project_id'] = 'fake'
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        return db.instance_create(None, inst)

    @defer.inlineCallbacks
    def test_run_describe_terminate(self):
        instance_id = self._create_instance()

        yield self.compute.run_instance(instance_id)

        instances = db.instance_get_all(None)
        logging.info("Running instances: %s", instances)
        self.assertEqual(len(instances), 1)

        yield self.compute.terminate_instance(instance_id)

        instances = db.instance_get_all(None)
        logging.info("After terminating instances: %s", instances)
        self.assertEqual(len(instances), 0)

    @defer.inlineCallbacks
    def test_reboot(self):
        instance_id = self._create_instance()
        yield self.compute.run_instance(instance_id)
        yield self.compute.reboot_instance(instance_id)
        yield self.compute.terminate_instance(instance_id)

    @defer.inlineCallbacks
    def test_console_output(self):
        instance_id = self._create_instance()
        rv = yield self.compute.run_instance(instance_id)

        console = yield self.compute.get_console_output(instance_id)
        self.assert_(console)
        rv = yield self.compute.terminate_instance(instance_id)

    @defer.inlineCallbacks
    def test_run_instance_existing(self):
        instance_id = self._create_instance()
        yield self.compute.run_instance(instance_id)
        self.assertFailure(self.compute.run_instance(instance_id), exception.Error)
        yield self.compute.terminate_instance(instance_id)
