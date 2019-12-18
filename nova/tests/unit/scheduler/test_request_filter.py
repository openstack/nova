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
import os_traits as ot

from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import timeutils

from nova import context as nova_context
from nova import exception
from nova.network import model as network_model
from nova import objects
from nova.scheduler import request_filter
from nova import test
from nova.tests.unit import utils


class TestRequestFilter(test.NoDBTestCase):
    def setUp(self):
        super(TestRequestFilter, self).setUp()
        self.context = nova_context.RequestContext(user_id=uuids.user,
                                                   project_id=uuids.project)
        self.flags(limit_tenants_to_placement_aggregate=True,
                   group='scheduler')
        self.flags(query_placement_for_availability_zone=True,
                   group='scheduler')
        self.flags(enable_isolated_aggregate_filtering=True,
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

    @mock.patch('nova.objects.aggregate.AggregateList.'
                'get_non_matching_by_metadata_keys')
    def test_isolate_aggregates(self, mock_getnotmd):
        agg4_traits = {'trait:HW_GPU_API_DXVA': 'required',
                       'trait:HW_NIC_DCB_ETS': 'required'}
        mock_getnotmd.return_value = [
            objects.Aggregate(
                uuid=uuids.agg1,
                metadata={'trait:CUSTOM_WINDOWS_LICENSED_TRAIT': 'required'}),
            objects.Aggregate(
                uuid=uuids.agg2,
                metadata={'trait:CUSTOM_WINDOWS_LICENSED_TRAIT': 'required',
                          'trait:CUSTOM_XYZ_TRAIT': 'required'}),
            objects.Aggregate(
                uuid=uuids.agg4,
                metadata=agg4_traits),
        ]
        fake_flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs=agg4_traits)
        fake_image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                traits_required=[]))
        reqspec = objects.RequestSpec(flavor=fake_flavor, image=fake_image)
        result = request_filter.isolate_aggregates(self.context, reqspec)
        self.assertTrue(result)
        self.assertItemsEqual(
            set([uuids.agg1, uuids.agg2, uuids.agg4]),
            reqspec.requested_destination.forbidden_aggregates)
        mock_getnotmd.assert_called_once_with(
            self.context, utils.ItemsMatcher(agg4_traits), 'trait:',
            value='required')

    @mock.patch('nova.objects.aggregate.AggregateList.'
                'get_non_matching_by_metadata_keys')
    def test_isolate_aggregates_union(self, mock_getnotmd):
        agg_traits = {'trait:HW_GPU_API_DXVA': 'required',
                      'trait:CUSTOM_XYZ_TRAIT': 'required'}
        mock_getnotmd.return_value = [
            objects.Aggregate(
                uuid=uuids.agg2,
                metadata={'trait:CUSTOM_WINDOWS_LICENSED_TRAIT': 'required',
                          'trait:CUSTOM_XYZ_TRAIT': 'required'}),
            objects.Aggregate(
                uuid=uuids.agg4,
                metadata={'trait:HW_GPU_API_DXVA': 'required',
                          'trait:HW_NIC_DCB_ETS': 'required'}),
        ]
        fake_flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs=agg_traits)
        fake_image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                traits_required=[]))
        reqspec = objects.RequestSpec(flavor=fake_flavor, image=fake_image)
        reqspec.requested_destination = objects.Destination(
            forbidden_aggregates={uuids.agg1})
        result = request_filter.isolate_aggregates(self.context, reqspec)
        self.assertTrue(result)
        self.assertEqual(
            ','.join(sorted([uuids.agg1, uuids.agg2, uuids.agg4])),
            ','.join(sorted(
                reqspec.requested_destination.forbidden_aggregates)))
        mock_getnotmd.assert_called_once_with(
            self.context, utils.ItemsMatcher(agg_traits), 'trait:',
            value='required')

    @mock.patch('nova.objects.aggregate.AggregateList.'
                'get_non_matching_by_metadata_keys')
    def test_isolate_agg_trait_on_flavor_destination_not_set(self,
                                                             mock_getnotmd):
        mock_getnotmd.return_value = []
        traits = set(['HW_GPU_API_DXVA', 'HW_NIC_DCB_ETS'])
        fake_flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'trait:' + trait: 'required' for trait in traits})
        fake_image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                traits_required=[]))
        reqspec = objects.RequestSpec(flavor=fake_flavor, image=fake_image)
        result = request_filter.isolate_aggregates(self.context, reqspec)
        self.assertTrue(result)
        self.assertNotIn('requested_destination', reqspec)
        keys = ['trait:%s' % trait for trait in traits]
        mock_getnotmd.assert_called_once_with(
            self.context, utils.ItemsMatcher(keys), 'trait:', value='required')

    @mock.patch('nova.objects.aggregate.AggregateList.'
                'get_non_matching_by_metadata_keys')
    def test_isolate_agg_trait_on_flv_img_destination_not_set(self,
                                                              mock_getnotmd):
        mock_getnotmd.return_value = []
        flavor_traits = set(['HW_GPU_API_DXVA'])
        image_traits = set(['HW_NIC_DCB_ETS'])
        fake_flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={
                'trait:' + trait: 'required' for trait in flavor_traits})
        fake_image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                traits_required=[trait for trait in image_traits]))
        reqspec = objects.RequestSpec(flavor=fake_flavor, image=fake_image)
        result = request_filter.isolate_aggregates(self.context, reqspec)
        self.assertTrue(result)
        self.assertNotIn('requested_destination', reqspec)
        keys = ['trait:%s' % trait for trait in flavor_traits.union(
            image_traits)]
        mock_getnotmd.assert_called_once_with(
            self.context, utils.ItemsMatcher(keys), 'trait:', value='required')

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

    @mock.patch('nova.objects.aggregate.AggregateList.'
                'get_non_matching_by_metadata_keys')
    @mock.patch('nova.objects.AggregateList.get_by_metadata')
    def test_with_tenant_and_az_and_traits(self, mock_getmd, mock_getnotmd):
        mock_getmd.side_effect = [
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

        mock_getnotmd.side_effect = [
            # isolate_aggregates filter
            [objects.Aggregate(
                uuid=uuids.agg1,
                metadata={'trait:CUSTOM_WINDOWS_LICENSED_TRAIT': 'required'}),
            objects.Aggregate(
                uuid=uuids.agg2,
                metadata={'trait:CUSTOM_WINDOWS_LICENSED_TRAIT': 'required',
                          'trait:CUSTOM_XYZ_TRAIT': 'required'}),
            objects.Aggregate(
                uuid=uuids.agg3,
                metadata={'trait:CUSTOM_XYZ_TRAIT': 'required'}),
            ],
        ]

        traits = set(['HW_GPU_API_DXVA', 'HW_NIC_DCB_ETS'])
        fake_flavor = objects.Flavor(
            vcpus=1, memory_mb=1024, root_gb=10, ephemeral_gb=5, swap=0,
            extra_specs={'trait:' + trait: 'required' for trait in traits})
        fake_image = objects.ImageMeta(
            properties=objects.ImageMetaProps(
                traits_required=[]))
        reqspec = objects.RequestSpec(project_id='owner',
                                      availability_zone='myaz',
                                      flavor=fake_flavor,
                                      image=fake_image)
        request_filter.process_reqspec(self.context, reqspec)
        self.assertEqual(
            ','.join(sorted([uuids.agg1, uuids.agg2])),
            ','.join(sorted(
                reqspec.requested_destination.aggregates[0].split(','))))
        self.assertEqual(
            ','.join(sorted([uuids.agg4])),
            ','.join(sorted(
                reqspec.requested_destination.aggregates[1].split(','))))
        self.assertItemsEqual(
            set([uuids.agg1, uuids.agg2, uuids.agg3]),
            reqspec.requested_destination.forbidden_aggregates)
        mock_getmd.assert_has_calls([
            mock.call(self.context, value='owner'),
            mock.call(self.context,
                      key='availability_zone',
                      value='myaz')])

        keys = ['trait:%s' % trait for trait in traits]
        mock_getnotmd.assert_called_once_with(
            self.context, utils.ItemsMatcher(keys), 'trait:', value='required')

    def test_require_image_type_support_disabled(self):
        self.flags(query_placement_for_image_type_support=False,
                   group='scheduler')
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}),
                                      is_bfv=False)
        # Assert that we completely skip the filter if disabled
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual(0, len(reqspec.root_forbidden))

    def test_require_image_type_support_volume_backed(self):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}),
                                      is_bfv=True)
        # Assert that we completely skip the filter if no image
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual(0, len(reqspec.root_forbidden))

    def test_require_image_type_support_unknown(self):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(
            image=objects.ImageMeta(disk_format='danformat'),
            flavor=objects.Flavor(extra_specs={}),
            is_bfv=False)
        # Assert that we completely skip the filter if no matching trait
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual(0, len(reqspec.root_forbidden))

    @mock.patch.object(request_filter, 'LOG')
    def test_require_image_type_support_adds_trait(self, mock_log):
        self.flags(query_placement_for_image_type_support=True,
                   group='scheduler')
        reqspec = objects.RequestSpec(
            image=objects.ImageMeta(disk_format='raw'),
            flavor=objects.Flavor(extra_specs={}),
            is_bfv=False)
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual(0, len(reqspec.root_forbidden))

        # Request filter puts the trait into the request spec
        request_filter.require_image_type_support(self.context, reqspec)
        self.assertEqual({ot.COMPUTE_IMAGE_TYPE_RAW}, reqspec.root_required)
        self.assertEqual(0, len(reqspec.root_forbidden))

        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('added required trait', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])

    @mock.patch.object(request_filter, 'LOG')
    def test_compute_status_filter(self, mock_log):
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}))
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual(0, len(reqspec.root_forbidden))

        # Request filter puts the trait into the request spec
        request_filter.compute_status_filter(self.context, reqspec)
        self.assertEqual(0, len(reqspec.root_required))
        self.assertEqual({ot.COMPUTE_STATUS_DISABLED}, reqspec.root_forbidden)

        # Assert both the in-method logging and trace decorator.
        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('added forbidden trait', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])

    @mock.patch.object(request_filter, 'LOG', new=mock.Mock())
    def test_transform_image_metadata(self):
        self.flags(image_metadata_prefilter=True, group='scheduler')
        properties = objects.ImageMetaProps(
            hw_disk_bus=objects.fields.DiskBus.SATA,
            hw_cdrom_bus=objects.fields.DiskBus.IDE,
            hw_video_model=objects.fields.VideoModel.QXL,
            hw_vif_model=network_model.VIF_MODEL_VIRTIO
        )
        reqspec = objects.RequestSpec(
            image=objects.ImageMeta(properties=properties),
            flavor=objects.Flavor(extra_specs={}),
        )
        self.assertTrue(
            request_filter.transform_image_metadata(None, reqspec)
        )
        expected = {
            'COMPUTE_GRAPHICS_MODEL_QXL',
            'COMPUTE_NET_VIF_MODEL_VIRTIO',
            'COMPUTE_STORAGE_BUS_IDE',
            'COMPUTE_STORAGE_BUS_SATA',
        }
        self.assertEqual(expected, reqspec.root_required)

    def test_transform_image_metadata__disabled(self):
        self.flags(image_metadata_prefilter=False, group='scheduler')
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}))
        # Assert that we completely skip the filter if disabled
        self.assertFalse(
            request_filter.transform_image_metadata(self.context, reqspec)
        )
        self.assertEqual(set(), reqspec.root_required)

    @mock.patch.object(request_filter, 'LOG')
    def test_accelerators_filter_with_device_profile(self, mock_log):
        # First ensure that accelerators_filter is included
        self.assertIn(request_filter.accelerators_filter,
                      request_filter.ALL_REQUEST_FILTERS)

        es = {'accel:device_profile': 'mydp'}
        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs=es))
        self.assertEqual(set(), reqspec.root_required)
        self.assertEqual(set(), reqspec.root_forbidden)

        # Request filter puts the trait into the request spec
        request_filter.accelerators_filter(self.context, reqspec)
        self.assertEqual({ot.COMPUTE_ACCELERATORS}, reqspec.root_required)
        self.assertEqual(set(), reqspec.root_forbidden)

        # Assert both the in-method logging and trace decorator.
        log_lines = [c[0][0] for c in mock_log.debug.call_args_list]
        self.assertIn('added required trait', log_lines[0])
        self.assertIn('took %.1f seconds', log_lines[1])

    @mock.patch.object(request_filter, 'LOG')
    def test_accelerators_filter_no_device_profile(self, mock_log):
        # First ensure that accelerators_filter is included
        self.assertIn(request_filter.accelerators_filter,
                      request_filter.ALL_REQUEST_FILTERS)

        reqspec = objects.RequestSpec(flavor=objects.Flavor(extra_specs={}))
        self.assertEqual(set(), reqspec.root_required)
        self.assertEqual(set(), reqspec.root_forbidden)

        # Request filter puts the trait into the request spec
        request_filter.accelerators_filter(self.context, reqspec)
        self.assertEqual(set(), reqspec.root_required)
        self.assertEqual(set(), reqspec.root_forbidden)

        # Assert about logging
        mock_log.assert_not_called()
