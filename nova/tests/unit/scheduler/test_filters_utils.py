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

from nova import objects
from nova.scheduler.filters import utils
from nova import test


_AGGREGATE_FIXTURES = [
    objects.Aggregate(
        id=1,
        name='foo',
        hosts=['fake-host'],
        metadata={'k1': '1', 'k2': '2'},
    ),
    objects.Aggregate(
        id=2,
        name='bar',
        hosts=['fake-host'],
        metadata={'k1': '3', 'k2': '4'},
    ),
]


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
        context = mock.MagicMock()
        get_by_host.return_value = objects.AggregateList(
            objects=_AGGREGATE_FIXTURES)

        values = utils.aggregate_values_from_db(context,
                                                'fake-host', key_name='k1')

        get_by_host.assert_called_with(context.elevated(),
                                       'fake-host', key='k1')
        self.assertEqual(set(['1', '3']), values)

    @mock.patch("nova.objects.aggregate.AggregateList.get_by_host")
    def test_aggregate_metadata_get_by_host_no_key(self, get_by_host):
        context = mock.MagicMock()
        get_by_host.return_value = objects.AggregateList(
            objects=_AGGREGATE_FIXTURES)

        metadata = utils.aggregate_metadata_get_by_host(context, 'fake-host')

        get_by_host.assert_called_with(context.elevated(),
                                       'fake-host', key=None)
        self.assertIn('k1', metadata)
        self.assertEqual(set(['1', '3']), metadata['k1'])
        self.assertIn('k2', metadata)
        self.assertEqual(set(['2', '4']), metadata['k2'])

    @mock.patch("nova.objects.aggregate.AggregateList.get_by_host")
    def test_aggregate_metadata_get_by_host_with_key(self, get_by_host):
        context = mock.MagicMock()
        get_by_host.return_value = objects.AggregateList(
            objects=_AGGREGATE_FIXTURES)

        metadata = utils.aggregate_metadata_get_by_host(context,
                                                        'fake-host', 'k1')

        get_by_host.assert_called_with(context.elevated(),
                                       'fake-host', key='k1')
        self.assertIn('k1', metadata)
        self.assertEqual(set(['1', '3']), metadata['k1'])

    @mock.patch("nova.objects.aggregate.AggregateList.get_by_host")
    def test_aggregate_metadata_get_by_host_empty_result(self, get_by_host):
        context = mock.MagicMock()
        get_by_host.return_value = objects.AggregateList(objects=[])

        metadata = utils.aggregate_metadata_get_by_host(context,
                                                        'fake-host', 'k3')

        get_by_host.assert_called_with(context.elevated(),
                                       'fake-host', key='k3')
        self.assertEqual({}, metadata)
