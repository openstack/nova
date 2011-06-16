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

from nova import exception
from nova import test
from nova.scheduler import driver
from nova.scheduler import zone_aware_scheduler
from nova.scheduler import zone_manager


def _host_caps(multiplier):
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


def fake_zone_manager_service_states(num_hosts):
    states = {}
    for x in xrange(num_hosts):
        states['host%02d' % (x + 1)] = {'compute': _host_caps(x)}
    return states


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
                'compute': {'ram': 1000},
            },
            'host2': {
                'compute': {'ram': 2000},
            },
            'host3': {
                'compute': {'ram': 3000},
            },
        }


class FakeEmptyZoneManager(zone_manager.ZoneManager):
    def __init__(self):
        self.service_states = {}


def fake_empty_call_zone_method(context, method, specs):
    return []


# Hmm, I should probably be using mox for this.
was_called = False


def fake_provision_resource(context, item, instance_id, request_spec, kwargs):
    global was_called
    was_called = True


def fake_ask_child_zone_to_create_instance(context, zone_info,
                                           request_spec, kwargs):
    global was_called
    was_called = True


def fake_provision_resource_locally(context, item, instance_id, kwargs):
    global was_called
    was_called = True


def fake_provision_resource_from_blob(context, item, instance_id,
                                      request_spec, kwargs):
    global was_called
    was_called = True


def fake_decrypt_blob_returns_local_info(blob):
    return {'foo': True}  # values aren't important.


def fake_decrypt_blob_returns_child_info(blob):
    return {'child_zone': True,
            'child_blob': True}  # values aren't important. Keys are.


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

    def test_schedule_do_not_schedule_with_hint(self):
        """
        Check the local/child zone routing in the run_instance() call.
        If the zone_blob hint was passed in, don't re-schedule.
        """
        global was_called
        sched = FakeZoneAwareScheduler()
        was_called = False
        self.stubs.Set(sched, '_provision_resource', fake_provision_resource)
        request_spec = {
                'instance_properties': {},
                'instance_type': {},
                'filter_driver': 'nova.scheduler.host_filter.AllHostsFilter',
                'blob': "Non-None blob data",
            }

        result = sched.schedule_run_instance(None, 1, request_spec)
        self.assertEquals(None, result)
        self.assertTrue(was_called)

    def test_provision_resource_local(self):
        """Provision a resource locally or remotely."""
        global was_called
        sched = FakeZoneAwareScheduler()
        was_called = False
        self.stubs.Set(sched, '_provision_resource_locally',
                       fake_provision_resource_locally)

        request_spec = {'hostname': "foo"}
        sched._provision_resource(None, request_spec, 1, request_spec, {})
        self.assertTrue(was_called)

    def test_provision_resource_remote(self):
        """Provision a resource locally or remotely."""
        global was_called
        sched = FakeZoneAwareScheduler()
        was_called = False
        self.stubs.Set(sched, '_provision_resource_from_blob',
                       fake_provision_resource_from_blob)

        request_spec = {}
        sched._provision_resource(None, request_spec, 1, request_spec, {})
        self.assertTrue(was_called)

    def test_provision_resource_from_blob_empty(self):
        """Provision a resource locally or remotely given no hints."""
        global was_called
        sched = FakeZoneAwareScheduler()
        request_spec = {}
        self.assertRaises(zone_aware_scheduler.InvalidBlob,
                          sched._provision_resource_from_blob,
                          None, {}, 1, {}, {})

    def test_provision_resource_from_blob_with_local_blob(self):
        """
        Provision a resource locally or remotely when blob hint passed in.
        """
        global was_called
        sched = FakeZoneAwareScheduler()
        was_called = False
        self.stubs.Set(sched, '_decrypt_blob',
                       fake_decrypt_blob_returns_local_info)
        self.stubs.Set(sched, '_provision_resource_locally',
                       fake_provision_resource_locally)

        request_spec = {'blob': "Non-None blob data"}

        sched._provision_resource_from_blob(None, request_spec, 1,
                                            request_spec, {})
        self.assertTrue(was_called)

    def test_provision_resource_from_blob_with_child_blob(self):
        """
        Provision a resource locally or remotely when child blob hint
        passed in.
        """
        global was_called
        sched = FakeZoneAwareScheduler()
        self.stubs.Set(sched, '_decrypt_blob',
                       fake_decrypt_blob_returns_child_info)
        was_called = False
        self.stubs.Set(sched, '_ask_child_zone_to_create_instance',
                       fake_ask_child_zone_to_create_instance)

        request_spec = {'blob': "Non-None blob data"}

        sched._provision_resource_from_blob(None, request_spec, 1,
                                            request_spec, {})
        self.assertTrue(was_called)

    def test_provision_resource_from_blob_with_immediate_child_blob(self):
        """
        Provision a resource locally or remotely when blob hint passed in
        from an immediate child.
        """
        global was_called
        sched = FakeZoneAwareScheduler()
        was_called = False
        self.stubs.Set(sched, '_ask_child_zone_to_create_instance',
                       fake_ask_child_zone_to_create_instance)

        request_spec = {'child_blob': True, 'child_zone': True}

        sched._provision_resource_from_blob(None, request_spec, 1,
                                            request_spec, {})
        self.assertTrue(was_called)
