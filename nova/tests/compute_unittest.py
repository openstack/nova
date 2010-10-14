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
"""
Tests For Compute
"""

import datetime
import logging

from twisted.internet import defer

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import utils
from nova.auth import manager

FLAGS = flags.FLAGS


class ComputeTestCase(test.TrialTestCase):
    """Test case for compute"""
    def setUp(self):  # pylint: disable-msg=C0103
        logging.getLogger().setLevel(logging.DEBUG)
        super(ComputeTestCase, self).setUp()
        self.flags(connection_type='fake',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = utils.import_object(FLAGS.compute_manager)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('fake', 'fake', 'fake')
        self.project = self.manager.create_project('fake', 'fake', 'fake')
        self.context = context.get_admin_context()

    def tearDown(self):  # pylint: disable-msg=C0103
        self.manager.delete_user(self.user)
        self.manager.delete_project(self.project)
        super(ComputeTestCase, self).tearDown()

    def _create_instance(self):
        """Create a test instance"""
        inst = {}
        inst['image_id'] = 'ami-test'
        inst['reservation_id'] = 'r-fakeres'
        inst['launch_time'] = '10'
        inst['user_id'] = self.user.id
        inst['project_id'] = self.project.id
        inst['instance_type'] = 'm1.tiny'
        inst['mac_address'] = utils.generate_mac()
        inst['ami_launch_index'] = 0
        return db.instance_create(self.context, inst)['id']

    @defer.inlineCallbacks
    def test_run_terminate(self):
        """Make sure it is possible to  run and terminate instance"""
        instance_id = self._create_instance()

        yield self.compute.run_instance(self.context, instance_id)

        instances = db.instance_get_all(context.get_admin_context())
        logging.info("Running instances: %s", instances)
        self.assertEqual(len(instances), 1)

        yield self.compute.terminate_instance(self.context, instance_id)

        instances = db.instance_get_all(context.get_admin_context())
        logging.info("After terminating instances: %s", instances)
        self.assertEqual(len(instances), 0)

    @defer.inlineCallbacks
    def test_run_terminate_timestamps(self):
        """Make sure timestamps are set for launched and destroyed"""
        instance_id = self._create_instance()
        instance_ref = db.instance_get(self.context, instance_id)
        self.assertEqual(instance_ref['launched_at'], None)
        self.assertEqual(instance_ref['deleted_at'], None)
        launch = datetime.datetime.utcnow()
        yield self.compute.run_instance(self.context, instance_id)
        instance_ref = db.instance_get(self.context, instance_id)
        self.assert_(instance_ref['launched_at'] > launch)
        self.assertEqual(instance_ref['deleted_at'], None)
        terminate = datetime.datetime.utcnow()
        yield self.compute.terminate_instance(self.context, instance_id)
        self.context = self.context.admin(True)
        instance_ref = db.instance_get(self.context, instance_id)
        self.assert_(instance_ref['launched_at'] < terminate)
        self.assert_(instance_ref['deleted_at'] > terminate)

    @defer.inlineCallbacks
    def test_reboot(self):
        """Ensure instance can be rebooted"""
        instance_id = self._create_instance()
        yield self.compute.run_instance(self.context, instance_id)
        yield self.compute.reboot_instance(self.context, instance_id)
        yield self.compute.terminate_instance(self.context, instance_id)

    @defer.inlineCallbacks
    def test_console_output(self):
        """Make sure we can get console output from instance"""
        instance_id = self._create_instance()
        yield self.compute.run_instance(self.context, instance_id)

        console = yield self.compute.get_console_output(self.context,
                                                        instance_id)
        self.assert_(console)
        yield self.compute.terminate_instance(self.context, instance_id)

    @defer.inlineCallbacks
    def test_run_instance_existing(self):
        """Ensure failure when running an instance that already exists"""
        instance_id = self._create_instance()
        yield self.compute.run_instance(self.context, instance_id)
        self.assertFailure(self.compute.run_instance(self.context,
                                                     instance_id),
                           exception.Error)
        yield self.compute.terminate_instance(self.context, instance_id)
