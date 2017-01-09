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
from six.moves import range

from nova import exception
from nova import objects
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

        self.driver._get_all_host_states(self.context, None)

        self.assertFalse(mock_up_hosts.called)
        self.assertEqual([], self.driver.all_host_states)

    @mock.patch.object(caching_scheduler.CachingScheduler,
                       "_get_up_hosts")
    def test_get_all_host_states_loads_hosts(self, mock_up_hosts):
        mock_up_hosts.return_value = ["asdf"]

        result = self.driver._get_all_host_states(self.context, None)

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
        spec_obj = self._get_fake_request_spec()
        self.driver.all_host_states = []

        self.assertRaises(exception.NoValidHost,
                self.driver.select_destinations,
                self.context, spec_obj)

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_select_destination_works(self, mock_get_extra):
        spec_obj = self._get_fake_request_spec()
        fake_host = self._get_fake_host_state()
        self.driver.all_host_states = [fake_host]

        result = self._test_select_destinations(spec_obj)

        self.assertEqual(1, len(result))
        self.assertEqual(result[0]["host"], fake_host.host)

    def _test_select_destinations(self, spec_obj):
        return self.driver.select_destinations(
                self.context, spec_obj)

    def _get_fake_request_spec(self):
        # NOTE(sbauza): Prevent to stub the Flavor.get_by_id call just by
        # directly providing a Flavor object
        flavor = objects.Flavor(
            flavorid="small",
            memory_mb=512,
            root_gb=1,
            ephemeral_gb=1,
            vcpus=1,
            swap=0,
        )
        instance_properties = {
            "os_type": "linux",
            "project_id": "1234",
        }
        request_spec = objects.RequestSpec(
            flavor=flavor,
            num_instances=1,
            ignore_hosts=None,
            force_hosts=None,
            force_nodes=None,
            retry=None,
            availability_zone=None,
            image=None,
            instance_group=None,
            pci_requests=None,
            numa_topology=None,
            instance_uuid='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
            **instance_properties
        )
        return request_spec

    def _get_fake_host_state(self, index=0):
        host_state = host_manager.HostState(
            'host_%s' % index,
            'node_%s' % index)
        host_state.free_ram_mb = 50000
        host_state.total_usable_ram_mb = 50000
        host_state.free_disk_mb = 4096
        host_state.total_usable_disk_gb = 4
        host_state.service = {
            "disabled": False,
            "updated_at": timeutils.utcnow(),
            "created_at": timeutils.utcnow(),
        }
        host_state.cpu_allocation_ratio = 16.0
        host_state.ram_allocation_ratio = 1.5
        host_state.disk_allocation_ratio = 1.0
        host_state.metrics = objects.MonitorMetricList(objects=[])
        return host_state

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_performance_check_select_destination(self, mock_get_extra):
        hosts = 2
        requests = 1

        self.flags(service_down_time=240)

        spec_obj = self._get_fake_request_spec()
        host_states = []
        for x in range(hosts):
            host_state = self._get_fake_host_state(x)
            host_states.append(host_state)
        self.driver.all_host_states = host_states

        def run_test():
            a = timeutils.utcnow()

            for x in range(requests):
                self.driver.select_destinations(
                    self.context, spec_obj)

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
                'testtools.*',
                'nova.tests.unit.*',
            ])
            graphviz = output.GraphvizOutput(output_file='scheduler.png')

            with pycallgraph.PyCallGraph(output=graphviz):
                per_request_ms = run_test()

        else:
            per_request_ms = run_test()

        # This has proved to be around 1 ms on a random dev box
        # But this is here so you can do simply performance testing easily.
        self.assertLess(per_request_ms, 1000)


if __name__ == '__main__':
    # A handy tool to help profile the schedulers performance
    ENABLE_PROFILER = True
    import testtools
    suite = testtools.ConcurrentTestSuite()
    test = "test_performance_check_select_destination"
    test_case = CachingSchedulerTestCase(test)
    suite.addTest(test_case)
    runner = testtools.TextTestResult.TextTestRunner()
    runner.run(suite)
