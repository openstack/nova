# Copyright (c) 2014 Rackspace Hosting
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

import mock
from oslo_utils import timeutils

from nova import exception
from nova.scheduler import caching_scheduler
from nova.scheduler import host_manager
from nova.tests.unit.scheduler import test_scheduler

ENABLE_PROFILER = False


class CachingSchedulerTestCase(test_scheduler.SchedulerTestCase):
    """Test case for Caching Scheduler."""

    driver_cls = caching_scheduler.CachingScheduler

    @mock.patch.object(caching_scheduler.CachingScheduler,
                       "_get_up_hosts")
    def test_run_periodic_tasks_loads_hosts(self, mock_up_hosts):
        mock_up_hosts.return_value = []
        context = mock.Mock()

        self.driver.run_periodic_tasks(context)

        self.assertTrue(mock_up_hosts.called)
        self.assertEqual([], self.driver.all_host_states)
        context.elevated.assert_called_with()

    @mock.patch.object(caching_scheduler.CachingScheduler,
                       "_get_up_hosts")
    def test_get_all_host_states_returns_cached_value(self, mock_up_hosts):
        self.driver.all_host_states = []

        self.driver._get_all_host_states(self.context)

        self.assertFalse(mock_up_hosts.called)
        self.assertEqual([], self.driver.all_host_states)

    @mock.patch.object(caching_scheduler.CachingScheduler,
                       "_get_up_hosts")
    def test_get_all_host_states_loads_hosts(self, mock_up_hosts):
        mock_up_hosts.return_value = ["asdf"]

        result = self.driver._get_all_host_states(self.context)

        self.assertTrue(mock_up_hosts.called)
        self.assertEqual(["asdf"], self.driver.all_host_states)
        self.assertEqual(["asdf"], result)

    def test_get_up_hosts(self):
        with mock.patch.object(self.driver.host_manager,
                               "get_all_host_states") as mock_get_hosts:
            mock_get_hosts.return_value = ["asdf"]

            result = self.driver._get_up_hosts(self.context)

            self.assertTrue(mock_get_hosts.called)
            self.assertEqual(mock_get_hosts.return_value, result)

    def test_select_destination_raises_with_no_hosts(self):
        fake_request_spec = self._get_fake_request_spec()
        self.driver.all_host_states = []

        self.assertRaises(exception.NoValidHost,
                self.driver.select_destinations,
                self.context, fake_request_spec, {})

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_select_destination_works(self, mock_get_extra):
        fake_request_spec = self._get_fake_request_spec()
        fake_host = self._get_fake_host_state()
        self.driver.all_host_states = [fake_host]

        result = self._test_select_destinations(fake_request_spec)

        self.assertEqual(1, len(result))
        self.assertEqual(result[0]["host"], fake_host.host)

    def _test_select_destinations(self, request_spec):
        return self.driver.select_destinations(
                self.context, request_spec, {})

    def _get_fake_request_spec(self):
        flavor = {
            "flavorid": "small",
            "memory_mb": 512,
            "root_gb": 1,
            "ephemeral_gb": 1,
            "vcpus": 1,
        }
        instance_properties = {
            "os_type": "linux",
            "project_id": "1234",
            "memory_mb": 512,
            "root_gb": 1,
            "ephemeral_gb": 1,
            "vcpus": 1,
            "uuid": 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        }
        request_spec = {
            "instance_type": flavor,
            "instance_properties": instance_properties,
            "num_instances": 1,
        }
        return request_spec

    def _get_fake_host_state(self, index=0):
        host_state = host_manager.HostState(
            'host_%s' % index,
            'node_%s' % index)
        host_state.free_ram_mb = 50000
        host_state.service = {
            "disabled": False,
            "updated_at": timeutils.utcnow(),
            "created_at": timeutils.utcnow(),
        }
        return host_state

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_performance_check_select_destination(self, mock_get_extra):
        hosts = 2
        requests = 1

        self.flags(service_down_time=240)

        request_spec = self._get_fake_request_spec()
        host_states = []
        for x in xrange(hosts):
            host_state = self._get_fake_host_state(x)
            host_states.append(host_state)
        self.driver.all_host_states = host_states

        def run_test():
            a = timeutils.utcnow()

            for x in xrange(requests):
                self.driver.select_destinations(
                    self.context, request_spec, {})

            b = timeutils.utcnow()
            c = b - a

            seconds = (c.days * 24 * 60 * 60 + c.seconds)
            microseconds = seconds * 1000 + c.microseconds / 1000.0
            per_request_ms = microseconds / requests
            return per_request_ms

        per_request_ms = None
        if ENABLE_PROFILER:
            import pycallgraph
            from pycallgraph import output
            config = pycallgraph.Config(max_depth=10)
            config.trace_filter = pycallgraph.GlobbingFilter(exclude=[
                'pycallgraph.*',
                'unittest.*',
                'nova.tests.unit.*',
            ])
            graphviz = output.GraphvizOutput(output_file='scheduler.png')

            with pycallgraph.PyCallGraph(output=graphviz):
                per_request_ms = run_test()

        else:
            per_request_ms = run_test()

        # This has proved to be around 1 ms on a random dev box
        # But this is here so you can do simply performance testing easily.
        self.assertTrue(per_request_ms < 1000)


if __name__ == '__main__':
    # A handy tool to help profile the schedulers performance
    ENABLE_PROFILER = True
    import unittest
    suite = unittest.TestSuite()
    test = "test_performance_check_select_destination"
    test_case = CachingSchedulerTestCase(test)
    suite.addTest(test_case)
    runner = unittest.TextTestRunner()
    runner.run(suite)
