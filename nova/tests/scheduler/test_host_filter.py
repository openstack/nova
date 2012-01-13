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

import nova
from nova import exception
from nova import test
from nova.scheduler import distributed_scheduler as dist
from nova.tests.scheduler import fake_zone_manager as ds_fakes


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
                'host_name-label': 'xs-%s' % multiplier,
                'enabled': True}

    def setUp(self):
        super(HostFilterTestCase, self).setUp()
        default_host_filters = ['AllHostsFilter']
        self.flags(default_host_filters=default_host_filters,
                reserved_host_disk_mb=0, reserved_host_memory_mb=0)
        self.instance_type = dict(name='tiny',
                memory_mb=30,
                vcpus=10,
                local_gb=300,
                flavorid=1,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200,
                extra_specs={})
        self.gpu_instance_type = dict(name='tiny.gpu',
                memory_mb=30,
                vcpus=10,
                local_gb=300,
                flavorid=2,
                swap=500,
                rxtx_quota=30000,
                rxtx_cap=200,
                extra_specs={'xpu_arch': 'fermi',
                             'xpu_info': 'Tesla 2050'})

        self.zone_manager = ds_fakes.FakeZoneManager()
        states = {}
        for x in xrange(4):
            states['host%d' % (x + 1)] = {'compute': self._host_caps(x)}
        self.zone_manager.service_states = states

        # Add some extra capabilities to some hosts
        host4 = self.zone_manager.service_states['host4']['compute']
        host4['xpu_arch'] = 'fermi'
        host4['xpu_info'] = 'Tesla 2050'

        host2 = self.zone_manager.service_states['host2']['compute']
        host2['xpu_arch'] = 'radeon'

        host3 = self.zone_manager.service_states['host3']['compute']
        host3['xpu_arch'] = 'fermi'
        host3['xpu_info'] = 'Tesla 2150'

    def _get_all_hosts(self):
        return self.zone_manager.get_all_host_data(None).items()

    def test_choose_filter(self):
        # Test default filter ...
        sched = dist.DistributedScheduler()
        hfs = sched._choose_host_filters()
        hf = hfs[0]
        self.assertEquals(hf._full_name().split(".")[-1], 'AllHostsFilter')
        # Test valid filter ...
        hfs = sched._choose_host_filters('InstanceTypeFilter')
        hf = hfs[0]
        self.assertEquals(hf._full_name().split(".")[-1], 'InstanceTypeFilter')
        # Test invalid filter ...
        try:
            sched._choose_host_filters('does not exist')
            self.fail("Should not find host filter.")
        except exception.SchedulerHostFilterNotFound:
            pass

    def test_all_host_filter(self):
        sched = dist.DistributedScheduler()
        hfs = sched._choose_host_filters('AllHostsFilter')
        hf = hfs[0]
        all_hosts = self._get_all_hosts()
        cooked = hf.instance_type_to_filter(self.instance_type)
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(4, len(hosts))
        for host, capabilities in hosts:
            self.assertTrue(host.startswith('host'))

    def test_instance_type_filter(self):
        hf = nova.scheduler.filters.InstanceTypeFilter()
        # filter all hosts that can support 30 ram and 300 disk
        cooked = hf.instance_type_to_filter(self.instance_type)
        all_hosts = self._get_all_hosts()
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(3, len(hosts))
        just_hosts = [host for host, hostinfo in hosts]
        just_hosts.sort()
        self.assertEquals('host4', just_hosts[2])
        self.assertEquals('host3', just_hosts[1])
        self.assertEquals('host2', just_hosts[0])

    def test_instance_type_filter_reserved_memory(self):
        self.flags(reserved_host_memory_mb=2048)
        hf = nova.scheduler.filters.InstanceTypeFilter()
        # filter all hosts that can support 30 ram and 300 disk after
        # reserving 2048 ram
        cooked = hf.instance_type_to_filter(self.instance_type)
        all_hosts = self._get_all_hosts()
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(2, len(hosts))
        just_hosts = [host for host, hostinfo in hosts]
        just_hosts.sort()
        self.assertEquals('host4', just_hosts[1])
        self.assertEquals('host3', just_hosts[0])

    def test_instance_type_filter_extra_specs(self):
        hf = nova.scheduler.filters.InstanceTypeFilter()
        # filter all hosts that can support 30 ram and 300 disk
        cooked = hf.instance_type_to_filter(self.gpu_instance_type)
        all_hosts = self._get_all_hosts()
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(1, len(hosts))
        just_hosts = [host for host, caps in hosts]
        self.assertEquals('host4', just_hosts[0])

    def test_json_filter(self):
        hf = nova.scheduler.filters.JsonFilter()
        # filter all hosts that can support 30 ram and 300 disk
        cooked = hf.instance_type_to_filter(self.instance_type)
        all_hosts = self._get_all_hosts()
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(2, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        self.assertEquals('host3', just_hosts[0])
        self.assertEquals('host4', just_hosts[1])

        # Try some custom queries

        raw = ['or',
                   ['and',
                       ['<', '$compute.host_memory_free', 30],
                       ['<', '$compute.disk_available', 300],
                   ],
                   ['and',
                       ['>', '$compute.host_memory_free', 30],
                       ['>', '$compute.disk_available', 300],
                   ]
              ]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(all_hosts, cooked, {})

        self.assertEquals(3, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([1, 2, 4], just_hosts):
            self.assertEquals('host%d' % index, host)

        raw = ['not',
                  ['=', '$compute.host_memory_free', 30],
              ]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(all_hosts, cooked, {})

        self.assertEquals(3, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([1, 2, 4], just_hosts):
            self.assertEquals('host%d' % index, host)

        raw = ['in', '$compute.host_memory_free', 20, 40, 60, 80, 100]
        cooked = json.dumps(raw)
        hosts = hf.filter_hosts(all_hosts, cooked, {})
        self.assertEquals(2, len(hosts))
        just_hosts = [host for host, caps in hosts]
        just_hosts.sort()
        for index, host in zip([2, 4], just_hosts):
            self.assertEquals('host%d' % index, host)

        # Try some bogus input ...
        raw = ['unknown command', ]
        cooked = json.dumps(raw)
        try:
            hf.filter_hosts(all_hosts, cooked, {})
            self.fail("Should give KeyError")
        except KeyError, e:
            pass

        self.assertTrue(hf.filter_hosts(all_hosts, json.dumps([]), {}))
        self.assertTrue(hf.filter_hosts(all_hosts, json.dumps({}), {}))
        self.assertTrue(hf.filter_hosts(all_hosts, json.dumps(
                ['not', True, False, True, False],
            ), {}))

        try:
            hf.filter_hosts(all_hosts, json.dumps(
                'not', True, False, True, False,), {})
            self.fail("Should give KeyError")
        except KeyError, e:
            pass

        self.assertFalse(hf.filter_hosts(all_hosts,
                json.dumps(['=', '$foo', 100]), {}))
        self.assertFalse(hf.filter_hosts(all_hosts,
                json.dumps(['=', '$.....', 100]), {}))
        self.assertFalse(hf.filter_hosts(all_hosts,
                json.dumps(
            ['>', ['and', ['or', ['not', ['<', ['>=', ['<=', ['in', ]]]]]]]]),
                                                                        {}))

        self.assertFalse(hf.filter_hosts(all_hosts,
                json.dumps(['=', {}, ['>', '$missing....foo']]), {}))
