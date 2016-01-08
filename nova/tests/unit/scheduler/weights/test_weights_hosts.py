# Copyright 2011-2014 IBM
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
Tests For Scheduler weights.
"""

from nova.scheduler import weights
from nova.scheduler.weights import affinity
from nova.scheduler.weights import io_ops
from nova.scheduler.weights import metrics
from nova.scheduler.weights import ram
from nova import test
from nova.tests.unit import matchers
from nova.tests.unit.scheduler import fakes


class TestWeighedHost(test.NoDBTestCase):
    def test_dict_conversion(self):
        host_state = fakes.FakeHostState('somehost', None, {})
        host = weights.WeighedHost(host_state, 'someweight')
        expected = {'weight': 'someweight',
                    'host': 'somehost'}
        self.assertThat(host.to_dict(), matchers.DictMatches(expected))

    def test_all_weighers(self):
        classes = weights.all_weighers()
        self.assertIn(ram.RAMWeigher, classes)
        self.assertIn(metrics.MetricsWeigher, classes)
        self.assertIn(io_ops.IoOpsWeigher, classes)
        self.assertIn(affinity.ServerGroupSoftAffinityWeigher, classes)
        self.assertIn(affinity.ServerGroupSoftAntiAffinityWeigher, classes)
