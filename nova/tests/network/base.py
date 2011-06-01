# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Rackspace
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import test
from nova.auth import manager
from nova.tests.db import fakes as db_fakes

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.network')


class NetworkTestCase(test.TestCase):
    def setUp(self):
        super(NetworkTestCase, self).setUp()
        self.flags(connection_type='fake',
                   fake_call=True,
                   fake_network=True,
                   network_manager=self.network_manager)
        self.manager = manager.AuthManager()
        self.user = self.manager.create_user('netuser',
                                             'netuser',
                                             'netuser')
        self.projects = []
        db_fakes.stub_out_db_network_api(self.stubs)
        self.network = utils.import_object(FLAGS.network_manager)
        self.context = context.RequestContext(project=None, user=self.user)


class TestFuncs(object):
    def test_set_network_host(self):
        host = "fake_test_host"
        self.assertEqual(self.network.set_network_host(self.context, host),
                         host)

    def test_allocate_for_instance(self):
        instance_id = 0
        project_id = 0
        type_id = 0
        ip = self.network.allocate_from_instance(self.context,
                                                 instance_id=instance_id,
                                                 project_id=project_id,
                                                 type_id=type_id)
        print ip
