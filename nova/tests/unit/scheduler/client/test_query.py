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

from nova import context
from nova import objects
from nova.scheduler.client import query
from nova import test
from nova.tests import uuidsentinel as uuids


class SchedulerQueryClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerQueryClientTestCase, self).setUp()
        self.context = context.get_admin_context()

        self.client = query.SchedulerQueryClient()

    def test_constructor(self):
        self.assertIsNotNone(self.client.scheduler_rpcapi)

    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_select_destinations(self, mock_select_destinations):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        self.client.select_destinations(
            context=self.context,
            spec_obj=fake_spec,
            instance_uuids=[fake_spec.instance_uuid],
            return_objects=True,
            return_alternates=True,
        )
        mock_select_destinations.assert_called_once_with(self.context,
                fake_spec, [fake_spec.instance_uuid], True, True)

    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.select_destinations')
    def test_select_destinations_old_call(self, mock_select_destinations):
        fake_spec = objects.RequestSpec()
        fake_spec.instance_uuid = uuids.instance
        self.client.select_destinations(
            context=self.context,
            spec_obj=fake_spec,
            instance_uuids=[fake_spec.instance_uuid]
        )
        mock_select_destinations.assert_called_once_with(self.context,
                fake_spec, [fake_spec.instance_uuid], False, False)

    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.update_aggregates')
    def test_update_aggregates(self, mock_update_aggs):
        aggregates = [objects.Aggregate(id=1)]
        self.client.update_aggregates(
            context=self.context,
            aggregates=aggregates)
        mock_update_aggs.assert_called_once_with(
            self.context, aggregates)

    @mock.patch('nova.scheduler.rpcapi.SchedulerAPI.delete_aggregate')
    def test_delete_aggregate(self, mock_delete_agg):
        aggregate = objects.Aggregate(id=1)
        self.client.delete_aggregate(
            context=self.context,
            aggregate=aggregate)
        mock_delete_agg.assert_called_once_with(
            self.context, aggregate)
