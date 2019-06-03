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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler import request_filter
from nova import test


class TestRequestFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestRequestFilter, self).setUp()
        self.context = nova_context.RequestContext(user_id=uuids.user,
                                                   project_id=uuids.project)
        self.flags(limit_tenants_to_placement_aggregate=True,
                   group='scheduler')
        self.flags(query_placement_for_availability_zone=True,
                   group='scheduler')

    def test_process_reqspec(self):
        fake_filters = [mock.MagicMock(), mock.MagicMock()]
        with mock.patch('nova.scheduler.request_filter.ALL_REQUEST_FILTERS',
                        new=fake_filters):
            request_filter.process_reqspec(mock.sentinel.context,
                                           mock.sentinel.reqspec)
        for filter in fake_filters:
            filter.assert_called_once_with(mock.sentinel.context,
                                           mock.sentinel.reqspec)

    @mock.patch.object(timeutils, 'now')
    def test_log_timer(self, mock_now):
        mock_now.return_value = 123
        result = False

        @request_filter.trace_request_filter
        def tester(c, r):
            mock_now.return_value += 2
            return result

        with mock.patch.object(request_filter, 'LOG') as log:
            # With a False return, no log should be emitted
            tester(None, None)
            log.debug.assert_not_called()

            # With a True return, elapsed time should be logged
            result = True
            tester(None, None)
            log.debug.assert_called_once_with('Request filter %r'
                                              ' took %.1f seconds',
                                              'tester', 2.0)

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_require_tenant_aggregate_disabled(self, getmd):
        self.flags(limit_tenants_to_placement_aggregate=False,
                   group='scheduler')
        reqspec = mock.MagicMock()
        request_filter.require_tenant_aggregate(self.context, reqspec)
        self.assertFalse(getmd.called)

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    @mock.patch.object(request_filter, 'LOG')
    def test_require_tenant_aggregate(self, mock_log, getmd):
        getmd.return_value = [
            objects.Aggregate(
                uuid=uuids.agg1,
                metadata={'filter_tenant_id': 'owner'}),
            objects.Aggregate(
                uuid=uuids.agg2,
                metadata={'filter_tenant_id:12': 'owner'}),
            objects.Aggregate(
                uuid=uuids.agg3,
                metadata={'other_key': 'owner'}),
        ]
        reqspec = objects.RequestSpec(project_id='owner')
        request_filter.require_tenant_aggregate(self.context, reqspec)
        self.assertEqual(
            ','.join(sorted([uuids.agg1, uuids.agg2])),
            ','.join(sorted(
                reqspec.requested_destination.aggregates[0].split(','))))
        # Make sure we called with the request spec's tenant and not
        # necessarily just the one from context.
        getmd.assert_called_once_with(self.context, value='owner')

        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('filter added aggregates', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_require_tenant_aggregate_no_match(self, getmd):
        self.flags(placement_aggregate_required_for_tenants=True,
                   group='scheduler')
        getmd.return_value = []
        self.assertRaises(exception.RequestFilterFailed,
                          request_filter.require_tenant_aggregate,
                          self.context, mock.MagicMock())

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_require_tenant_aggregate_no_match_not_required(self, getmd):
        getmd.return_value = []
        request_filter.require_tenant_aggregate(
            self.context, mock.MagicMock())

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    @mock.patch.object(request_filter, 'LOG')
    def test_map_az(self, mock_log, getmd):
        getmd.return_value = [objects.Aggregate(uuid=uuids.agg1)]
        reqspec = objects.RequestSpec(availability_zone='fooaz')
        request_filter.map_az_to_placement_aggregate(self.context, reqspec)
        self.assertEqual([uuids.agg1],
                         reqspec.requested_destination.aggregates)
        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('filter added aggregates', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_map_az_no_hint(self, getmd):
        reqspec = objects.RequestSpec(availability_zone=None)
        request_filter.map_az_to_placement_aggregate(self.context, reqspec)
        self.assertNotIn('requested_destination', reqspec)
        self.assertFalse(getmd.called)

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_map_az_no_aggregates(self, getmd):
        getmd.return_value = []
        reqspec = objects.RequestSpec(availability_zone='fooaz')
        request_filter.map_az_to_placement_aggregate(self.context, reqspec)
        self.assertNotIn('requested_destination', reqspec)
        getmd.assert_called_once_with(self.context, key='availability_zone',
                                      value='fooaz')

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_map_az_disabled(self, getmd):
        self.flags(query_placement_for_availability_zone=False,
                   group='scheduler')
        reqspec = objects.RequestSpec(availability_zone='fooaz')
        request_filter.map_az_to_placement_aggregate(self.context, reqspec)
        getmd.assert_not_called()

    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_with_tenant_and_az(self, getmd):
        getmd.side_effect = [
            # Tenant filter
            [objects.Aggregate(
                uuid=uuids.agg1,
                metadata={'filter_tenant_id': 'owner'}),
            objects.Aggregate(
                uuid=uuids.agg2,
                metadata={'filter_tenant_id:12': 'owner'}),
            objects.Aggregate(
                uuid=uuids.agg3,
                metadata={'other_key': 'owner'})],
            # AZ filter
            [objects.Aggregate(
                uuid=uuids.agg4,
                metadata={'availability_zone': 'myaz'})],
        ]
        reqspec = objects.RequestSpec(project_id='owner',
                                      availability_zone='myaz')
        request_filter.process_reqspec(self.context, reqspec)
        self.assertEqual(
            ','.join(sorted([uuids.agg1, uuids.agg2])),
            ','.join(sorted(
                reqspec.requested_destination.aggregates[0].split(','))))
        self.assertEqual(
            ','.join(sorted([uuids.agg4])),
            ','.join(sorted(
                reqspec.requested_destination.aggregates[1].split(','))))
        getmd.assert_has_calls([
            mock.call(self.context, value='owner'),
            mock.call(self.context,
                      key='availability_zone',
                      value='myaz')])

    def test_require_image_type_support_disabled(self):
        self.flags(query_placement_for_image_type_support=False,
                   group='scheduler')
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}),
                                      is_bfv=False)
        # Assert that we completely skip the filter if disabled
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual({}, reqspec.flavor.extra_specs)

    def test_require_image_type_support_volume_backed(self):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}),
                                      is_bfv=True)
        # Assert that we completely skip the filter if no image
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual({}, reqspec.flavor.extra_specs)

    def test_require_image_type_support_unknown(self):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(
            image=objects.ImageMeta(disk_format='danformat'),
            flavor=objects.Flavor(extra_specs={}),
            is_bfv=False)
        # Assert that we completely skip the filter if no matching trait
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual({}, reqspec.flavor.extra_specs)

    @mock.patch.object(request_filter, 'LOG')
    def test_require_image_type_support_adds_trait(self, mock_log):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(
            image=objects.ImageMeta(disk_format='raw'),
            flavor=objects.Flavor(extra_specs={}),
            is_bfv=False)
        # Assert that we add the trait to the flavor as required
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual({'trait:COMPUTE_IMAGE_TYPE_RAW': 'required'},
                         reqspec.flavor.extra_specs)
        self.assertEqual(set(), reqspec.flavor.obj_what_changed())

        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('added required trait', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])
