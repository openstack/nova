# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 Cloud.com, Inc
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
Tests For Hyper-V driver
"""

import random

from nova import db
from nova import flags
from nova import test

from nova.virt import hyperv

FLAGS = flags.FLAGS
FLAGS.connection_type = 'hyperv'
# Redis is probably not  running on Hyper-V host.
# Change this to the actual Redis host
FLAGS.redis_host = '127.0.0.1'


class HyperVTestCase(test.TrialTestCase):
    """Test cases for the Hyper-V driver"""
    def setUp(self):  # pylint: disable-msg=C0103
        pass

    def test_create_destroy(self):
        """Create a VM and destroy it"""
        instance = {'internal_id': random.randint(1, 1000000),
                     'memory_mb': '1024',
                     'mac_address': '02:12:34:46:56:67',
                     'vcpu': 2,
                     'project_id': 'fake',
                     'instance_type': 'm1.small'}

        instance_ref = db.instance_create(None, instance)

        conn = hyperv.get_connection(False)
        conn._create_vm(instance_ref)  # pylint: disable-msg=W0212
        found = [n  for n in conn.list_instances()
                      if n == instance_ref['name']]
        self.assertTrue(len(found) == 1)
        info = conn.get_info(instance_ref['name'])
        #Unfortunately since the vm is not running at this point,
        #we cannot obtain memory information from get_info
        self.assertEquals(info['num_cpu'], instance_ref['vcpus'])

        conn.destroy(instance_ref)
        found = [n  for n in conn.list_instances()
                      if n == instance_ref['name']]
        self.assertTrue(len(found) == 0)

    def tearDown(self):  # pylint: disable-msg=C0103
        pass
