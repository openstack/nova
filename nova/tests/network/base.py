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
from nova import utils
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
        self.network = utils.import_object(FLAGS.network_manager)
        db_fakes.stub_out_db_network_api(self.stubs)
        self.network.db = db
        self.context = context.RequestContext(project=None, user=self.user)

    def tearDown(self):
        super(NetworkTestCase, self).tearDown()
        reload(db)


class TestFuncs(object):
    def test_set_network_hosts(self):
        db_fakes.stub_out_db_network_api(self.stubs, host=None)
        self.network.set_network_hosts(self.context)

    def test_set_network_host(self):
        host = self.network.host
        self.assertEqual(self.network.set_network_host(self.context, 0),
                         host)

    def test_allocate_for_instance(self):
        instance_id = 0
        project_id = 0
        type_id = 0
        nw = self.network.allocate_for_instance(self.context,
                                                instance_id=instance_id,
                                                project_id=project_id,
                                                instance_type_id=type_id)
        static_info = [({'bridge': 'fa0'},
                        {'broadcast': '192.168.0.255',
                         'dns': ['192.168.0.1'],
                         'gateway': '192.168.0.1',
                         'gateway6': 'dead:beef::1',
                         'ip6s': [{'enabled': '1',
                                   'ip': 'dead:beef::dcad:beff:feef:0',
                                         'netmask': '64'}],
                         'ips': [{'enabled': '1',
                                  'ip': '192.168.0.100',
                                  'netmask': '255.255.255.0'}],
                         'label': 'fake',
                         'mac': 'DE:AD:BE:EF:00:00',
                         'rxtx_cap': 3})]
        self.assertEqual(static_info, nw)

    def test_deallocate_for_instance(self):
        pass
