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
from nova.tests import uuidsentinel as uuids

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
        self.driver.all_host_states = {uuids.cell: []}

        self.driver._get_all_host_states(self.context, None,
            mock.sentinel.provider_uuids)

        self.assertFalse(mock_up_hosts.called)
        self.assertEqual({uuids.cell: []}, self.driver.all_host_states)

    @mock.patch.object(caching_scheduler.CachingScheduler,
                       "_get_up_hosts")
    def test_get_all_host_states_loads_hosts(self, mock_up_hosts):
        host_state = self._get_fake_host_state()
        mock_up_hosts.return_value = {uuids.cell: [host_state]}

        result = self.driver._get_all_host_states(self.context, None,
            mock.sentinel.provider_uuids)

        self.assertTrue(mock_up_hosts.called)
        self.assertEqual({uuids.cell: [host_state]},
                         self.driver.all_host_states)
        self.assertEqual([host_state], list(result))

    def test_get_up_hosts(self):
        with mock.patch.object(self.driver.host_manager,
                               "get_all_host_states") as mock_get_hosts:
            host_state = self._get_fake_host_state()
            mock_get_hosts.return_value = [host_state]

            result = self.driver._get_up_hosts(self.context)

            self.assertTrue(mock_get_hosts.called)
            self.assertEqual({uuids.cell: [host_state]}, result)

    def test_select_destination_raises_with_no_hosts(self):
        spec_obj = self._get_fake_request_spec()
        self.driver.all_host_states = {uuids.cell: []}

        self.assertRaises(exception.NoValidHost,
                self.driver.select_destinations,
                self.context, spec_obj, [spec_obj.instance_uuid],
                {}, {})

    @mock.patch('nova.db.instance_extra_get_by_instance_uuid',
                return_value={'numa_topology': None,
                              'pci_requests': None})
    def test_select_destination_works(self, mock_get_extra):
        spec_obj = self._get_fake_request_spec()
        fake_host = self._get_fake_host_state()
        self.driver.all_host_states = {uuids.cell: [fake_host]}

        result = self._test_select_destinations(spec_obj)

        self.assertEqual(1, len(result))
        self.assertEqual(result[0][0].service_host, fake_host.host)

    def _test_select_destinations(self, spec_obj):
        provider_summaries = {}
        for cell_hosts in self.driver.all_host_states.values():
            for hs in cell_hosts:
                provider_summaries[hs.uuid] = hs

        return self.driver.select_destinations(
                self.context, spec_obj, [spec_obj.instance_uuid], {},
                provider_summaries)

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
            'node_%s' % index,
            uuids.cell)
        host_state.uuid = getattr(uuids, 'host_%s' % index)
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
        host_state.failed_builds = 0
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
        self.driver.all_host_states = {uuids.cell: host_states}
        provider_summaries = {hs.uuid: hs for hs in host_states}

        def run_test():
            a = timeutils.utcnow()

            for x in range(requests):
                self.driver.select_destinations(self.context, spec_obj,
                        [spec_obj.instance_uuid], {}, provider_summaries)

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

    def test_request_single_cell(self):
        spec_obj = self._get_fake_request_spec()
        spec_obj.requested_destination = objects.Destination(
            cell=objects.CellMapping(uuid=uuids.cell2))
        host_states_cell1 = [self._get_fake_host_state(i)
                             for i in range(1, 5)]
        host_states_cell2 = [self._get_fake_host_state(i)
                             for i in range(5, 10)]

        self.driver.all_host_states = {
            uuids.cell1: host_states_cell1,
            uuids.cell2: host_states_cell2,
        }
        provider_summaries = {
            cn.uuid: cn for cn in host_states_cell1 + host_states_cell2
        }

        d = self.driver.select_destinations(self.context, spec_obj,
                [spec_obj.instance_uuid], {}, provider_summaries)
        self.assertIn(d[0][0].service_host,
                [hs.host for hs in host_states_cell2])

    @mock.patch("nova.scheduler.host_manager.HostState.consume_from_request")
    @mock.patch("nova.scheduler.caching_scheduler.CachingScheduler."
                "_get_sorted_hosts")
    @mock.patch("nova.scheduler.caching_scheduler.CachingScheduler."
                "_get_all_host_states")
    def test_alternates_same_cell(self, mock_get_all_hosts, mock_sorted,
            mock_consume):
        """Tests getting hosts plus alternates where the hosts are spread
        across two cells.
        """
        all_host_states = []
        for num in range(10):
            host_name = "host%s" % num
            cell_uuid = uuids.cell1 if num % 2 else uuids.cell2
            hs = host_manager.HostState(host_name, "node%s" % num,
                    cell_uuid)
            hs.uuid = getattr(uuids, host_name)
            all_host_states.append(hs)

        mock_get_all_hosts.return_value = all_host_states
        # There are two instances, so _get_sorted_hosts will be called once
        # per instance, and then once again before picking alternates.
        mock_sorted.side_effect = [all_host_states,
                                   list(reversed(all_host_states)),
                                   all_host_states]
        total_returned = 3
        self.flags(max_attempts=total_returned, group="scheduler")
        instance_uuids = [uuids.inst1, uuids.inst2]
        num_instances = len(instance_uuids)

        spec_obj = objects.RequestSpec(
                num_instances=num_instances,
                flavor=objects.Flavor(memory_mb=512,
                                      root_gb=512,
                                      ephemeral_gb=0,
                                      swap=0,
                                      vcpus=1),
                project_id=uuids.project_id,
                instance_group=None)

        dests = self.driver._schedule(self.context, spec_obj,
                instance_uuids, None, None, return_alternates=True)
        # There should be max_attempts hosts per instance (1 selected, 2 alts)
        self.assertEqual(total_returned, len(dests[0]))
        self.assertEqual(total_returned, len(dests[1]))
        # Verify that the two selected hosts are not in the same cell.
        self.assertNotEqual(dests[0][0].cell_uuid, dests[1][0].cell_uuid)
        for dest in dests:
            selected_host = dest[0]
            selected_cell_uuid = selected_host.cell_uuid
            for alternate in dest[1:]:
                self.assertEqual(alternate.cell_uuid, selected_cell_uuid)


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
