# Copyright 2011 OpenStack LLC. 
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
Tests For Scheduler Query Drivers
"""

from nova import exception
from nova import flags
from nova import test
from nova.scheduler import query

FLAGS = flags.FLAGS

class FakeZoneManager:
    pass

class QueryTestCase(test.TestCase):
    """Test case for query drivers."""

    def _host_caps(self, multiplier):
        return {'host_name-description':'XenServer %s' % multiplier,
                'host_hostname':'xs-%s' % multiplier,
                'host_memory':{'total': 100,
                             'overhead': 5,
                             'free': 5 + multiplier * 5,
                             'free-computed': 5 + multiplier * 5},
                'host_other-config':{},
                'host_ip_address':'192.168.1.%d' % (100 + multiplier),
                'host_cpu_info':{},
                'disk':{'available': 100 + multiplier * 100,
                      'total': 1000,
                      'used': 50 + multiplier * 50},
                'host_uuid':'xxx-%d' % multiplier,
                'host_name-label':'xs-%s' % multiplier}

    def setUp(self):
        self.old_flag = FLAGS.default_query_engine
        FLAGS.default_query_engine = 'nova.scheduler.query.AllHostsQuery'
        self.instance_type = dict(name='tiny',
                memory_mb=500,
                vcpus=10,
                local_gb=50,
                flavorid=1,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200)

        hosts = {}
        for x in xrange(10):
            hosts['host%s' % x] = self._host_caps(x)

        self.zone_manager = FakeZoneManager()
        self.zone_manager.service_states = {}
        self.zone_manager.service_states['compute'] = hosts

    def tearDown(self):
        FLAGS.default_query_engine = self.old_flag

    def test_choose_driver(self):
        driver = query.choose_driver()
        self.assertEquals(str(driver), 'nova.scheduler.query.AllHostsQuery')
        driver = query.choose_driver('nova.scheduler.query.FlavorQuery')
        self.assertEquals(str(driver), 'nova.scheduler.query.FlavorQuery')
        try:
            query.choose_driver('does not exist')
            self.fail("Should not find driver")
        except exception.SchedulerQueryDriverNotFound:
            pass

    def test_all_host_driver(self):
        driver = query.AllHostsQuery()
        cooked = driver.instance_type_to_query(self.instance_type)
        hosts = driver.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(10, len(hosts))
        for host, capabilities in hosts:
            self.assertTrue(host.startswith('host'))

