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
    def _compare_fields(self, dict1, dict2, fields):
        for field in fields:
            self.assertEqual(dict1[field], dict2[field])

    def test_set_network_hosts(self):
        self.network.set_network_hosts(self.context)

    def test_set_network_host(self):
        host = self.network.host
        self.assertEqual(self.network.set_network_host(self.context, 0),
                         host)

    def test_allocate_for_instance(self):
        instance_id = 0
        project_id = 0
        type_id = 0
        self.network.set_network_hosts(self.context)
        nw = self.network.allocate_for_instance(self.context,
                                                instance_id=instance_id,
                                                project_id=project_id,
                                                instance_type_id=type_id)
        static_info = [({'bridge': 'fa0', 'id': 0},
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

        self._compare_fields(nw[0][0], static_info[0][0], ('bridge',))
        self._compare_fields(nw[0][1], static_info[0][1], ('ips',
                                                           'broadcast',
                                                           'gateway',
                                                           'ip6s'))

    def test_deallocate_for_instance(self):
        instance_id = 0
        network_id = 0
        self.network.set_network_hosts(self.context)
        self.network.add_fixed_ip_to_instance(self.context,
                                              instance_id=instance_id,
                                              network_id=network_id)
        ips = db.fixed_ip_get_by_instance(self.context, instance_id)
        for ip in ips:
            self.assertTrue(ip['allocated'])
        self.network.deallocate_for_instance(self.context,
                                             instance_id=instance_id)
        ips = db.fixed_ip_get_by_instance(self.context, instance_id)
        for ip in ips:
            self.assertFalse(ip['allocated'])

    def test_lease_release_fixed_ip(self):
        instance_id = 0
        project_id = 0
        type_id = 0
        self.network.set_network_hosts(self.context)
        nw = self.network.allocate_for_instance(self.context,
                                                instance_id=instance_id,
                                                project_id=project_id,
                                                instance_type_id=type_id)
        self.assertTrue(nw)
        self.assertTrue(nw[0])
        network_id = nw[0][0]['id']

        ips = db.fixed_ip_get_by_instance(self.context, instance_id)
        mac = db.mac_address_get_by_instance_and_network(self.context,
                                                         instance_id,
                                                         network_id)
        self.assertTrue(ips)
        address = ips[0]['address']

        db.fixed_ip_associate(self.context, address, instance_id)
        db.fixed_ip_update(self.context, address,
                           {'mac_address_id': mac['id']})

        self.network.lease_fixed_ip(self.context, mac['address'], address)
        ip = db.fixed_ip_get_by_address(self.context, address)
        self.assertTrue(ip['leased'])

        self.network.release_fixed_ip(self.context, mac['address'], address)
        ip = db.fixed_ip_get_by_address(self.context, address)
        self.assertFalse(ip['leased'])
