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

from nova import objects
from nova.scheduler.filters import retry_filter
from nova import test
from nova.tests.unit.scheduler import fakes


class TestRetryFilter(test.NoDBTestCase):

    def setUp(self):
        super(TestRetryFilter, self).setUp()
        self.filt_cls = retry_filter.RetryFilter()
        self.assertIn('The RetryFilter is deprecated',
                      self.stdlog.logger.output)

    def test_retry_filter_disabled(self):
        # Test case where retry/re-scheduling is disabled.
        host = fakes.FakeHostState('host1', 'node1', {})
        spec_obj = objects.RequestSpec(retry=None)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_retry_filter_pass(self):
        # Node not previously tried.
        host = fakes.FakeHostState('host1', 'nodeX', {})
        retry = objects.SchedulerRetries(
            num_attempts=2,
            hosts=objects.ComputeNodeList(objects=[
                # same host, different node
                objects.ComputeNode(host='host1', hypervisor_hostname='node1'),
                # different host and node
                objects.ComputeNode(host='host2', hypervisor_hostname='node2'),
            ]))
        spec_obj = objects.RequestSpec(retry=retry)
        self.assertTrue(self.filt_cls.host_passes(host, spec_obj))

    def test_retry_filter_fail(self):
        # Node was already tried.
        host = fakes.FakeHostState('host1', 'node1', {})
        retry = objects.SchedulerRetries(
            num_attempts=1,
            hosts=objects.ComputeNodeList(objects=[
                objects.ComputeNode(host='host1', hypervisor_hostname='node1')
            ]))
        spec_obj = objects.RequestSpec(retry=retry)
        self.assertFalse(self.filt_cls.host_passes(host, spec_obj))
