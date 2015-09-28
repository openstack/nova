# Copyright 2011-2012 OpenStack Foundation
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
Tests For weights.
"""

import mock

from nova.scheduler import weights as scheduler_weights
from nova.scheduler.weights import ram
from nova import test
from nova.tests.unit.scheduler import fakes
from nova import weights


class TestWeigher(test.NoDBTestCase):
    def test_no_multiplier(self):
        class FakeWeigher(weights.BaseWeigher):
            def _weigh_object(self, *args, **kwargs):
                pass

        self.assertEqual(1.0,
                         FakeWeigher().weight_multiplier())

    def test_no_weight_object(self):
        class FakeWeigher(weights.BaseWeigher):
            def weight_multiplier(self, *args, **kwargs):
                pass
        self.assertRaises(TypeError,
                          FakeWeigher)

    def test_normalization(self):
        # weight_list, expected_result, minval, maxval
        map_ = (
            ((), (), None, None),
            ((0.0, 0.0), (0.0, 0.0), None, None),
            ((1.0, 1.0), (0.0, 0.0), None, None),

            ((20.0, 50.0), (0.0, 1.0), None, None),
            ((20.0, 50.0), (0.0, 0.375), None, 100.0),
            ((20.0, 50.0), (0.4, 1.0), 0.0, None),
            ((20.0, 50.0), (0.2, 0.5), 0.0, 100.0),
        )
        for seq, result, minval, maxval in map_:
            ret = weights.normalize(seq, minval=minval, maxval=maxval)
            self.assertEqual(tuple(ret), result)

    @mock.patch('nova.weights.BaseWeigher.weigh_objects')
    def test_only_one_host(self, mock_weigh):
        host_values = [
            ('host1', 'node1', {'free_ram_mb': 512}),
        ]
        hostinfo = [fakes.FakeHostState(host, node, values)
                    for host, node, values in host_values]

        weight_handler = scheduler_weights.HostWeightHandler()
        weighers = [ram.RAMWeigher()]
        weighed_host = weight_handler.get_weighed_objects(weighers,
                                                          hostinfo, {})
        self.assertEqual(1, len(weighed_host))
        self.assertEqual('host1', weighed_host[0].obj.host)
        self.assertFalse(mock_weigh.called)
