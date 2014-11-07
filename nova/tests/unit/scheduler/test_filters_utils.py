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

from nova.scheduler.filters import utils
from nova import test


class UtilsTestCase(test.NoDBTestCase):
    def test_validate_num_values(self):
        f = utils.validate_num_values

        self.assertEqual("x", f(set(), default="x"))
        self.assertEqual(1, f(set(["1"]), cast_to=int))
        self.assertEqual(1.0, f(set(["1"]), cast_to=float))
        self.assertEqual(1, f(set([1, 2]), based_on=min))
        self.assertEqual(2, f(set([1, 2]), based_on=max))

    @mock.patch("nova.objects.aggregate.AggregateList.get_by_host")
    def test_aggregate_values_from_db(self, get_by_host):
        aggrA = mock.MagicMock()
        aggrB = mock.MagicMock()
        context = mock.MagicMock()

        get_by_host.return_value = [aggrA, aggrB]
        aggrA.metadata = {'k1': 1, 'k2': 2}
        aggrB.metadata = {'k1': 3, 'k2': 4}

        values = utils.aggregate_values_from_db(context, 'h1', key_name='k1')

        self.assertTrue(context.elevated.called)
        self.assertEqual(set([1, 3]), values)
