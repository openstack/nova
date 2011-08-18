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
Tests For Scheduler Host Filters.
"""

import json

from nova import exception
from nova import test
from nova.scheduler import host_filter
from nova.scheduler import filters


class FakeZoneManager:
    pass


class HostFilterTestCase(test.TestCase):
    """Test case for host filters."""

    def _host_caps(self, multiplier):
        # Returns host capabilities in the following way:
        # host1 = memory:free 10 (100max)
        #         disk:available 100 (1000max)
        # hostN = memory:free 10 + 10N
        #         disk:available 100 + 100N
        # in other words: hostN has more resources than host0
        # which means ... don't go above 10 hosts.
        return {'host_name-description': 'XenServer %s' % multiplier,
                'host_hostname': 'xs-%s' % multiplier,
                'host_memory_total': 100,
                'host_memory_overhead': 10,
                'host_memory_free': 10 + multiplier * 10,
                'host_memory_free-computed': 10 + multiplier * 10,
                'host_other-config': {},
                'host_ip_address': '192.168.1.%d' % (100 + multiplier),
                'host_cpu_info': {},
                'disk_available': 100 + multiplier * 100,
                'disk_total': 1000,
                'disk_used': 0,
                'host_uuid': 'xxx-%d' % multiplier,
                'host_name-label': 'xs-%s' % multiplier}

    def setUp(self):
        super(HostFilterTestCase, self).setUp()
        default_host_filter = 'AllHostsFilter'
        self.flags(default_host_filter=default_host_filter)
        self.instance_type = dict(name='tiny',
                memory_mb=50,
                vcpus=10,
                local_gb=500,
                flavorid=1,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200,
                extra_specs={})
        self.gpu_instance_type = dict(name='tiny.gpu',
                memory_mb=50,
                vcpus=10,
                local_gb=500,
                flavorid=2,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200,
                extra_specs={'xpu_arch': 'fermi',
                             'xpu_info': 'Tesla 2050'})

        self.zone_manager = FakeZoneManager()
        states = {}
        for x in xrange(10):
            states['host%02d' % (x + 1)] = {'compute': self._host_caps(x)}
        self.zone_manager.service_states = states

        # Add some extra capabilities to some hosts
        host07 = self.zone_manager.service_states['host07']['compute']
        host07['xpu_arch'] = 'fermi'
        host07['xpu_info'] = 'Tesla 2050'

        host08 = self.zone_manager.service_states['host08']['compute']
        host08['xpu_arch'] = 'radeon'

        host09 = self.zone_manager.service_states['host09']['compute']
        host09['xpu_arch'] = 'fermi'
        host09['xpu_info'] = 'Tesla 2150'

    def test_choose_filter(self):
        # Test default filter ...
        hf = host_filter.choose_host_filter()
        self.assertEquals(hf._full_name().split(".")[-1], 'AllHostsFilter')
        # Test valid filter ...
        hf = host_filter.choose_host_filter('InstanceTypeFilter')
        self.assertEquals(hf._full_name().split(".")[-1], 'InstanceTypeFilter')
        # Test invalid filter ...
        try:
            host_filter.choose_host_filter('does not exist')
            self.fail("Should not find host filter.")
        except exception.SchedulerHostFilterNotFound:
            pass

    def test_all_host_filter(self):
        hf = filters.AllHostsFilter()
        cooked = hf.instance_type_to_filter(self.instance_type)
        hosts = hf.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(10, len(hosts))
        for host, capabilities in hosts:
            self.assertTrue(host.startswith('host'))

    def test_instance_type_filter(self):
        hf = filters.InstanceTypeFilter()
        # filter all hosts that can support 50 ram and 500 disk
        name, cooked = hf.instance_type_to_filter(self.instance_type)
        self.assertEquals(name.split(".")[-1], 'InstanceTypeFilter')
        hosts = hf.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(6, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        self.assertEquals('host05', just_hosts[0])
        self.assertEquals('host10', just_hosts[5])

    def test_instance_type_filter_extra_specs(self):
        hf = filters.InstanceTypeFilter()
        # filter all hosts that can support 50 ram and 500 disk
        name, cooked = hf.instance_type_to_filter(self.gpu_instance_type)
        self.assertEquals(name.split(".")[-1], 'InstanceTypeFilter')
        hosts = hf.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(1, len(hosts))
        just_hosts = [host for host, caps in hosts]
        self.assertEquals('host07', just_hosts[0])

    def test_json_filter(self):
        hf = filters.JsonFilter()
        # filter all hosts that can support 50 ram and 500 disk
        name, cooked = hf.instance_type_to_filter(self.instance_type)
        self.assertEquals(name.split(".")[-1], 'JsonFilter')
        hosts = hf.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(6, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        self.assertEquals('host05', just_hosts[0])
        self.assertEquals('host10', just_hosts[5])

        # Try some custom queries

        raw = ['or',
                   ['and',
                       ['<', '$compute.host_memory_free', 30],
                       ['<', '$compute.disk_available', 300],
                   ],
                   ['and',
                       ['>', '$compute.host_memory_free', 70],
                       ['>', '$compute.disk_available', 700],
                   ]
              ]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(self.zone_manager, cooked)

        self.assertEquals(5, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([1, 2, 8, 9, 10], just_hosts):
            self.assertEquals('host%02d' % index, host)

        raw = ['not',
                  ['=', '$compute.host_memory_free', 30],
              ]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(self.zone_manager, cooked)

        self.assertEquals(9, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([1, 2, 4, 5, 6, 7, 8, 9, 10], just_hosts):
            self.assertEquals('host%02d' % index, host)

        raw = ['in', '$compute.host_memory_free', 20, 40, 60, 80, 100]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(self.zone_manager, cooked)
        self.assertEquals(5, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([2, 4, 6, 8, 10], just_hosts):
            self.assertEquals('host%02d' % index, host)

        # Try some bogus input ...
        raw = ['unknown command', ]
        cooked = json.dumps(raw)
        try:
            hf.filter_hosts(self.zone_manager, cooked)
            self.fail("Should give KeyError")
        except KeyError, e:
            pass

        self.assertTrue(hf.filter_hosts(self.zone_manager, json.dumps([])))
        self.assertTrue(hf.filter_hosts(self.zone_manager, json.dumps({})))
        self.assertTrue(hf.filter_hosts(self.zone_manager, json.dumps(
                ['not', True, False, True, False],
            )))

        try:
            hf.filter_hosts(self.zone_manager, json.dumps(
                'not', True, False, True, False,
            ))
            self.fail("Should give KeyError")
        except KeyError, e:
            pass

        self.assertFalse(hf.filter_hosts(self.zone_manager,
                json.dumps(['=', '$foo', 100])))
        self.assertFalse(hf.filter_hosts(self.zone_manager,
                json.dumps(['=', '$.....', 100])))
        self.assertFalse(hf.filter_hosts(self.zone_manager,
                json.dumps(
            ['>', ['and', ['or', ['not', ['<', ['>=', ['<=', ['in', ]]]]]]]])))

        self.assertFalse(hf.filter_hosts(self.zone_manager,
                json.dumps(['=', {}, ['>', '$missing....foo']])))
