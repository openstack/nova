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
Tests For Scheduler image properties weights.
"""
from unittest import mock

from oslo_utils.fixture import uuidsentinel as uuids

from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler import weights
from nova.scheduler.weights import image_props
from nova import test
from nova.tests.unit.scheduler import fakes

PROP_PC = objects.ImageMeta(
    properties=objects.ImageMetaProps(hw_machine_type='pc'))

PROP_WIN_PC = objects.ImageMeta(
    properties=objects.ImageMetaProps(os_distro='windows',
                                      hw_machine_type='pc'))

PROP_LIN = objects.ImageMeta(
    properties=objects.ImageMetaProps(os_distro='linux'))

PROP_LIN_PC = objects.ImageMeta(
    properties=objects.ImageMetaProps(os_distro='linux', hw_machine_type='pc'))


class _ImagePropertiesWeigherBase(test.NoDBTestCase):

    def setUp(self):
        super().setUp()
        self.weight_handler = weights.HostWeightHandler()
        self.weighers = [image_props.ImagePropertiesWeigher()]

        self.stub_out('nova.objects.ImageMeta.from_instance',
                      self._fake_image_meta_from_instance)

    @staticmethod
    def _fake_image_meta_from_instance(self, inst):
        # inst1 is on host2
        if inst.uuid == uuids.inst1:
            return PROP_WIN_PC
        # inst2 and inst3 are on host3
        elif inst.uuid == uuids.inst2:
            return PROP_LIN
        elif inst.uuid == uuids.inst3:
            return PROP_LIN_PC
        # inst4 is on host4
        elif inst.uuid == uuids.inst4:
            return PROP_LIN
        else:
            return objects.ImageMeta(properties=objects.ImageMetaProps())

    def _get_weighed_host(self, hosts, request_spec=None):
        if request_spec is None:
            request_spec = objects.RequestSpec(image=None)
        return self.weight_handler.get_weighed_objects(self.weighers,
                hosts, request_spec)[0]

    def _get_all_hosts(self):

        host_values = [
            # host1 has no instances
            ('host1', 'node1', {'instances': {}}),
            # host2 has one instance with os_distro=win and hw_machine_type=pc
            ('host2', 'node2', {'instances': {uuids.inst1: objects.Instance(
                                                        uuid=uuids.inst1)}}),
            # host3 has two instances
            # (os_distro=lin twice, hw_machine_type=pc only once)
            ('host3', 'node3', {'instances': {uuids.inst2: objects.Instance(
                                                        uuid=uuids.inst2),
                                              uuids.inst3: objects.Instance(
                                                        uuid=uuids.inst3)}}),
            # host4 has one instance with os_distro=lin only
            ('host4', 'node4', {'instances': {uuids.inst2: objects.Instance(
                                                        uuid=uuids.inst4)}}),

        ]
        return [fakes.FakeHostState(host, node, values)
                for host, node, values in host_values]


class ImagePropertiesWeigherTestCase(_ImagePropertiesWeigherBase):

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    def test_multiplier_default(self, mock_fm):
        hostinfo_list = self._get_all_hosts()
        weighed_host = self._get_weighed_host(hostinfo_list)
        self.assertEqual(0.0, weighed_host.weight)
        # Nothing changes, we just returns the first in the list
        self.assertEqual('host1', weighed_host.obj.host)
        mock_fm.assert_not_called()

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    def test_multiplier_windows_and_pc(self, mock_fm):
        self.flags(image_props_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        # we request for both windows and pc machine type
        weighed_host = self._get_weighed_host(
            hostinfo_list,
            request_spec=objects.RequestSpec(
                image=PROP_WIN_PC))
        self.assertEqual(1.0, weighed_host.weight)
        # only host2 has instances with both os_distro=windows and
        # hw_machine_type=pc
        self.assertEqual('host2', weighed_host.obj.host)
        mock_fm.assert_has_calls([mock.call(), mock.call(),
                                  mock.call(), mock.call()])

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    def test_multiplier_pc(self, mock_fm):
        self.flags(image_props_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        weights = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list,
            weighing_properties=objects.RequestSpec(image=PROP_PC))
        # host2 and host3 have instances with pc machine type so are equally
        # weighed so we return the first of both.
        expected_weights = [{'weight': 1.0, 'host': 'host2'},
                            {'weight': 1.0, 'host': 'host3'},
                            {'weight': 0.0, 'host': 'host1'},
                            {'weight': 0.0, 'host': 'host4'}]
        self.assertEqual(expected_weights, [weigh.to_dict()
                                            for weigh in weights])
        self.assertEqual('host2', weights[0].obj.host)
        mock_fm.assert_has_calls([mock.call(), mock.call(),
                                  mock.call(), mock.call()])

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    def test_multiplier_linux(self, mock_fm):
        self.flags(image_props_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()
        weights = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list,
            weighing_properties=objects.RequestSpec(image=PROP_LIN))
        # host3 and host4 have instances with linux distro but we favor
        # host3 given he has more instances having the same requested property
        expected_weights = [{'weight': 1.0, 'host': 'host3'},
                            {'weight': 0.5, 'host': 'host4'},
                            {'weight': 0.0, 'host': 'host1'},
                            {'weight': 0.0, 'host': 'host2'}]
        self.assertEqual(expected_weights, [weigh.to_dict()
                                            for weigh in weights])
        self.assertEqual('host3', weights[0].obj.host)
        mock_fm.assert_has_calls([mock.call(), mock.call(),
                                  mock.call(), mock.call()])

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    def test_multiplier_per_property(self, mock_fm):
        self.flags(image_props_weight_multiplier=1.0, group='filter_scheduler')
        hostinfo_list = self._get_all_hosts()

        # For now, don't exclude any property check and boot with an image
        # using both hw_machine_type and os_distro properties.
        weights = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list,
            weighing_properties=objects.RequestSpec(image=PROP_LIN_PC))
        # host3 is preferred as it has both of the correct properties with
        # the right values.
        # host2 and host4 only support one of each property.
        expected_weights = [{'weight': 1.0, 'host': 'host3'},
                            {'weight': (1 / 3), 'host': 'host2'},
                            {'weight': (1 / 3), 'host': 'host4'},
                            {'weight': 0.0, 'host': 'host1'}]
        self.assertEqual(expected_weights, [weigh.to_dict()
                                            for weigh in weights])
        self.assertEqual('host3', weights[0].obj.host)

        # Now, let's exclude hw_machine_type property to be weighed.
        self.flags(image_props_weight_setting=['os_distro=1',
                                               'hw_machine_type=0'],
                   group='filter_scheduler')
        # Force a refresh of the settings since we updated them
        self.weighers[0]._parse_setting()
        weights = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list,
            weighing_properties=objects.RequestSpec(image=PROP_LIN_PC))
        # host3 and host4 have instances with linux distro but we favor
        # host3 given he has more instances having the same requested property
        expected_weights = [{'weight': 1.0, 'host': 'host3'},
                            {'weight': 0.5, 'host': 'host4'},
                            {'weight': 0.0, 'host': 'host1'},
                            {'weight': 0.0, 'host': 'host2'}]
        self.assertEqual(expected_weights, [weigh.to_dict()
                                            for weigh in weights])
        self.assertEqual('host3', weights[0].obj.host)
        mock_fm.assert_has_calls([mock.call(), mock.call(),
                                  mock.call(), mock.call()])


class TestTargetCellCalled(_ImagePropertiesWeigherBase):
    # Using real cell infrastructure instead of SingleCellSimple fixture
    # as we need to verify set_target_cell calls are made
    USES_DB_SELF = True

    @mock.patch('nova.objects.InstanceList.fill_metadata')
    @mock.patch.object(nova_context, 'set_target_cell')
    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    @mock.patch.object(nova_context.RequestContext, 'from_dict')
    @mock.patch.object(nova_context, 'get_admin_context')
    def test_target_cell_called(self, mock_get_admin_context, mock_from_dict,
                                mock_get_by_uuid, mock_target_cell, mock_fm):
        fake_context = nova_context.RequestContext(is_admin=True)
        fake_cell_ctx = nova_context.RequestContext(is_admin=True)
        # let's simulate that we set a cell context as target_cell calls
        # from_dict internally
        mock_from_dict.return_value = fake_cell_ctx
        mock_get_admin_context.return_value = fake_context
        self.flags(image_props_weight_multiplier=1.0, group='filter_scheduler')

        fake_cell_mapping = objects.CellMapping(uuid=uuids.cell1)
        mock_get_by_uuid.side_effect = [fake_cell_mapping, fake_cell_mapping,
                                        # host3 won't have a cell mapping
                                        exception.CellMappingNotFound(
                                            uuid=uuids.cell2)]

        # Just create three hosts with only one instance, we just want to test
        # the calls to target_cell and fill_metadata.
        hostinfo_list = [
            fakes.FakeHostState('host1', 'node1',
                               {'instances': {uuids.inst1: objects.Instance(
                                               uuid=uuids.inst1)},
                                'cell_uuid': uuids.cell1}),
            fakes.FakeHostState('host2', 'node2',
                               {'instances': {}, 'cell_uuid': uuids.cell1}),
            # host3 is in a different cell
            fakes.FakeHostState('host3', 'node3',
                                {'instances': {}, 'cell_uuid': uuids.cell2}),
        ]
        request_spec = objects.RequestSpec(image=PROP_WIN_PC)

        weights = self.weight_handler.get_weighed_objects(
            self.weighers, hostinfo_list, weighing_properties=request_spec)

        mock_get_by_uuid.assert_has_calls([
            mock.call(fake_context, uuids.cell1),
            mock.call(fake_context, uuids.cell1),
            mock.call(fake_context, uuids.cell2)])

        # Now we see that set_target_cell is called with the cell context only
        # twice given host3 does not have a cell mapping
        mock_target_cell.assert_has_calls(
            [mock.call(fake_cell_ctx, fake_cell_mapping),
             mock.call(fake_cell_ctx, fake_cell_mapping)])

        # Ensure that fill_metadata was called with the correct context
        def _fake_fill_metadata(_self):
            self.assertEqual(fake_cell_ctx, _self._context)
        mock_fm.side_effect = _fake_fill_metadata

        # Double check that we called it only twice
        self.assertEqual(2, mock_fm.call_count)

        # host1 wins but we return all three hosts.
        self.assertEqual(3, len(weights))
        self.assertEqual('host1', weights[0].obj.host)
