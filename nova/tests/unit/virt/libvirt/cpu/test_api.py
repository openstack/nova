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

from unittest import mock

from nova import exception
from nova import objects
from nova import test
from nova.virt.libvirt.cpu import api
from nova.virt.libvirt.cpu import core


class TestAPI(test.NoDBTestCase):

    def setUp(self):
        super(TestAPI, self).setUp()
        self.core_1 = api.Core(1)
        self.api = api.API()

        # Create a fake instance with two pinned CPUs but only one is on the
        # dedicated set
        numa_topology = objects.InstanceNUMATopology(cells=[
            objects.InstanceNUMACell(cpu_pinning_raw={'0': '0', '2': '2'}),
        ])
        self.fake_inst = objects.Instance(numa_topology=numa_topology)

    @mock.patch.object(core, 'get_online')
    def test_online(self, mock_get_online):
        mock_get_online.return_value = True
        self.assertTrue(self.core_1.online)
        mock_get_online.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_online')
    def test_set_online(self, mock_set_online):
        self.core_1.online = True
        mock_set_online.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_offline')
    def test_set_offline(self, mock_set_offline):
        self.core_1.online = False
        mock_set_offline.assert_called_once_with(self.core_1.ident)

    def test_hash(self):
        self.assertEqual(hash(self.core_1.ident), hash(self.core_1))

    @mock.patch.object(core, 'get_governor')
    def test_governor(self, mock_get_governor):
        mock_get_governor.return_value = 'fake_governor'
        self.assertEqual('fake_governor', self.core_1.governor)
        mock_get_governor.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'get_governor')
    def test_governor_optional(self, mock_get_governor):
        mock_get_governor.side_effect = exception.FileNotFound(file_path='foo')
        self.assertIsNone(self.core_1.governor)
        mock_get_governor.assert_called_once_with(self.core_1.ident)

    @mock.patch.object(core, 'set_governor')
    def test_set_governor_low(self, mock_set_governor):
        self.flags(cpu_power_governor_low='fake_low_gov', group='libvirt')
        self.core_1.set_low_governor()
        mock_set_governor.assert_called_once_with(self.core_1.ident,
                                                  'fake_low_gov')

    @mock.patch.object(core, 'set_governor')
    def test_set_governor_high(self, mock_set_governor):
        self.flags(cpu_power_governor_high='fake_high_gov', group='libvirt')
        self.core_1.set_high_governor()
        mock_set_governor.assert_called_once_with(self.core_1.ident,
                                                  'fake_high_gov')

    @mock.patch.object(core, 'set_online')
    def test_power_up_online(self, mock_online):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='1-2', group='compute')

        self.api.power_up_for_instance(self.fake_inst)
        # only core #2 can be set as core #0 is not on the dedicated set
        # As a reminder, core(i).online calls set_online(i)
        mock_online.assert_called_once_with(2)

    @mock.patch.object(core, 'set_governor')
    def test_power_up_governor(self, mock_set_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        self.flags(cpu_dedicated_set='1-2', group='compute')

        self.api.power_up_for_instance(self.fake_inst)
        # only core #2 can be set as core #1 is not on the dedicated set
        # As a reminder, core(i).set_high_governor calls set_governor(i)
        mock_set_governor.assert_called_once_with(2, 'performance')

    @mock.patch.object(core, 'set_online')
    def test_power_up_skipped(self, mock_online):
        self.flags(cpu_power_management=False, group='libvirt')
        self.api.power_up_for_instance(self.fake_inst)
        mock_online.assert_not_called()

    @mock.patch.object(core, 'set_online')
    def test_power_up_skipped_if_standard_instance(self, mock_online):
        self.flags(cpu_power_management=True, group='libvirt')
        self.api.power_up_for_instance(objects.Instance(numa_topology=None))
        mock_online.assert_not_called()

    @mock.patch.object(core, 'set_offline')
    def test_power_down_offline(self, mock_offline):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='1-2', group='compute')

        self.api.power_down_for_instance(self.fake_inst)
        # only core #2 can be set as core #1 is not on the dedicated set
        # As a reminder, core(i).online calls set_online(i)
        mock_offline.assert_called_once_with(2)

    @mock.patch.object(core, 'set_governor')
    def test_power_down_governor_cpu0_ignored(self, mock_set_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        self.flags(cpu_dedicated_set='0-1', group='compute')

        self.api.power_down_for_instance(self.fake_inst)

        # Make sure that core #0 is ignored, since it is special and cannot
        # be powered down.
        mock_set_governor.assert_not_called()

    @mock.patch.object(core, 'set_governor')
    def test_power_down_governor(self, mock_set_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        self.flags(cpu_dedicated_set='1-2', group='compute')

        self.api.power_down_for_instance(self.fake_inst)

        # only core #2 can be set as core #0 is not on the dedicated set
        # As a reminder, core(i).set_high_governor calls set_governor(i)
        mock_set_governor.assert_called_once_with(2, 'powersave')

    @mock.patch.object(core, 'set_offline')
    def test_power_down_skipped(self, mock_offline):
        self.flags(cpu_power_management=False, group='libvirt')
        self.api.power_down_for_instance(self.fake_inst)
        mock_offline.assert_not_called()

    @mock.patch.object(core, 'set_offline')
    def test_power_down_skipped_if_standard_instance(self, mock_offline):
        self.flags(cpu_power_management=True, group='libvirt')
        self.api.power_down_for_instance(objects.Instance(numa_topology=None))
        mock_offline.assert_not_called()

    @mock.patch.object(core, 'set_offline')
    def test_power_down_all_dedicated_cpus_offline(self, mock_offline):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='0-2', group='compute')

        self.api.power_down_all_dedicated_cpus()
        # All dedicated CPUs are turned offline, except CPU0
        mock_offline.assert_has_calls([mock.call(1), mock.call(2)])

    @mock.patch.object(core, 'set_governor')
    def test_power_down_all_dedicated_cpus_governor(self, mock_set_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        self.flags(cpu_dedicated_set='0-2', group='compute')

        self.api.power_down_all_dedicated_cpus()
        # All dedicated CPUs are turned offline, except CPU0
        mock_set_governor.assert_has_calls([mock.call(1, 'powersave'),
                                            mock.call(2, 'powersave')])

    @mock.patch.object(core, 'set_offline')
    def test_power_down_all_dedicated_cpus_skipped(self, mock_offline):
        self.flags(cpu_power_management=False, group='libvirt')
        self.api.power_down_all_dedicated_cpus()
        mock_offline.assert_not_called()

    @mock.patch.object(core, 'set_offline')
    def test_power_down_all_dedicated_cpus_no_dedicated_cpus_configured(
        self, mock_offline
    ):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set=None, group='compute')
        self.api.power_down_all_dedicated_cpus()
        mock_offline.assert_not_called()

    @mock.patch.object(core, 'get_governor')
    @mock.patch.object(core, 'get_online')
    def test_validate_all_dedicated_cpus_for_governor(self, mock_get_online,
                                                      mock_get_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='0-1', group='compute')
        self.flags(cpu_power_management_strategy='governor', group='libvirt')
        mock_get_governor.return_value = 'performance'
        mock_get_online.side_effect = (True, False)
        self.assertRaises(exception.InvalidConfiguration,
                          self.api.validate_all_dedicated_cpus)

    @mock.patch.object(core, 'get_governor')
    @mock.patch.object(core, 'get_online')
    def test_validate_all_dedicated_cpus_for_cpu_state(self, mock_get_online,
                                                       mock_get_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='1-2', group='compute')
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')
        mock_get_online.return_value = True
        mock_get_governor.side_effect = ('powersave', 'performance')
        self.assertRaises(exception.InvalidConfiguration,
                          self.api.validate_all_dedicated_cpus)

    @mock.patch.object(core, 'get_governor')
    @mock.patch.object(core, 'get_online')
    @mock.patch.object(api.LOG, 'warning')
    def test_validate_all_dedicated_cpus_for_cpu_state_warning(
        self, mock_warning, mock_get_online, mock_get_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='0-2', group='compute')
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')

        mock_get_online.return_value = True
        mock_get_governor.return_value = 'performance'

        self.api.validate_all_dedicated_cpus()

        # Make sure we skipped CPU0
        mock_get_online.assert_has_calls([mock.call(1), mock.call(2)])

        # Make sure we logged a warning about CPU0
        mock_warning.assert_called_once_with(
            'CPU0 is in cpu_dedicated_set, but it is not eligible for '
            'state management and will be ignored')

    def test_validate_all_dedicated_cpus_no_cpu(self):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set=None, group='compute')
        self.api.validate_all_dedicated_cpus()
        # no assert we want to make sure the validation won't raise if
        # no dedicated cpus are configured

    @mock.patch.object(core, 'get_governor')
    @mock.patch.object(core, 'get_online')
    def test_validate_all_dedicated_cpus_for_cpu_state_with_off_cores(
            self, mock_get_online, mock_get_governor):
        self.flags(cpu_power_management=True, group='libvirt')
        self.flags(cpu_dedicated_set='1-3', group='compute')
        self.flags(cpu_power_management_strategy='cpu_state', group='libvirt')
        # CPU1 and CPU3 are online while CPU2 is offline
        mock_get_online.side_effect = (True, False, True)
        mock_get_governor.return_value = 'performance'
        self.api.validate_all_dedicated_cpus()

        mock_get_online.assert_has_calls([mock.call(1), mock.call(2),
                                          mock.call(3)])
        # we only have two calls as CPU2 was skipped
        mock_get_governor.assert_has_calls([mock.call(1),
                                            mock.call(3)])
