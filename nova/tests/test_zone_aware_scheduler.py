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
Tests For Zone Aware Scheduler.
"""

from nova import test
from nova.scheduler import driver
from nova.scheduler import zone_aware_scheduler
from nova.scheduler import zone_manager


class FakeZoneAwareScheduler(zone_aware_scheduler.ZoneAwareScheduler):
    def filter_hosts(self, num, specs):
        # NOTE(sirp): this is returning [(hostname, services)]
        return self.zone_manager.service_states.items()

    def weigh_hosts(self, num, specs, hosts):
        fake_weight = 99
        weighted = []
        for hostname, caps in hosts:
            weighted.append(dict(weight=fake_weight, name=hostname))
        return weighted


class FakeZoneManager(zone_manager.ZoneManager):
    def __init__(self):
        self.service_states = {
                        'host1': {
                            'compute': {'ram': 1000}
                         },
                         'host2': {
                            'compute': {'ram': 2000}
                         },
                         'host3': {
                            'compute': {'ram': 3000}
                         }
                     }


class FakeEmptyZoneManager(zone_manager.ZoneManager):
    def __init__(self):
        self.service_states = {}


def fake_empty_call_zone_method(context, method, specs):
    return []


def fake_call_zone_method(context, method, specs):
    return [
        ('zone1', [
            dict(weight=1, blob='AAAAAAA'),
            dict(weight=111, blob='BBBBBBB'),
            dict(weight=112, blob='CCCCCCC'),
            dict(weight=113, blob='DDDDDDD'),
        ]),
        ('zone2', [
            dict(weight=120, blob='EEEEEEE'),
            dict(weight=2, blob='FFFFFFF'),
            dict(weight=122, blob='GGGGGGG'),
            dict(weight=123, blob='HHHHHHH'),
        ]),
        ('zone3', [
            dict(weight=130, blob='IIIIIII'),
            dict(weight=131, blob='JJJJJJJ'),
            dict(weight=132, blob='KKKKKKK'),
            dict(weight=3, blob='LLLLLLL'),
        ]),
    ]


class ZoneAwareSchedulerTestCase(test.TestCase):
    """Test case for Zone Aware Scheduler."""

    def test_zone_aware_scheduler(self):
        """
        Create a nested set of FakeZones, ensure that a select call returns the
        appropriate build plan.
        """
        sched = FakeZoneAwareScheduler()
        self.stubs.Set(sched, '_call_zone_method', fake_call_zone_method)

        zm = FakeZoneManager()
        sched.set_zone_manager(zm)

        fake_context = {}
        build_plan = sched.select(fake_context, {})

        self.assertEqual(15, len(build_plan))

        hostnames = [plan_item['name']
                     for plan_item in build_plan if 'name' in plan_item]
        self.assertEqual(3, len(hostnames))

    def test_empty_zone_aware_scheduler(self):
        """
        Ensure empty hosts & child_zones result in NoValidHosts exception.
        """
        sched = FakeZoneAwareScheduler()
        self.stubs.Set(sched, '_call_zone_method', fake_empty_call_zone_method)

        zm = FakeEmptyZoneManager()
        sched.set_zone_manager(zm)

        fake_context = {}
        self.assertRaises(driver.NoValidHost, sched.schedule_run_instance,
                          fake_context, 1,
                          dict(host_filter=None,
                               request_spec={'instance_type': {}}))
