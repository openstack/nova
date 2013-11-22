# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import inspect

from nova.scheduler import filters
from nova.scheduler import host_manager
from nova import test
from nova.virt import driver


class IronicAPIContractsTestCase(test.NoDBTestCase):

    def _check_method(self, method, str_version, expected_args):
        spec = inspect.getargspec(method)
        self.assertEqual(expected_args, spec.args,
                         "%s() violates Ironic contract" % str_version)

    def test_HostState_signatures(self):
        self._check_method(host_manager.HostState.__init__,
                           "HostState.__init__",
                           ['self', 'host', 'node', 'compute'])

    def test_HostManager_signatures(self):
        self._check_method(host_manager.HostManager.__init__,
                           "HostManager.__init__",
                           ['self'])

    def test_BaseHostFilter_signatures(self):
        self._check_method(filters.BaseHostFilter.host_passes,
                           "BaseHostFilter.host_passes",
                           ['self', 'host_state', 'filter_properties'])

    def test_ComputeDriver_signatures(self):
        self._check_method(driver.ComputeDriver.__init__,
                           "ComputeDriver.__init__",
                           ['self', 'virtapi'])

        self._check_method(driver.ComputeDriver.init_host,
                           "ComputeDriver.init_host",
                           ['self', 'host'])

        self._check_method(driver.ComputeDriver.get_info,
                           "ComputeDriver.get_info",
                           ['self', 'instance'])

        self._check_method(driver.ComputeDriver.instance_exists,
                           "ComputeDriver.instance_exists",
                           ['self', 'instance'])

        self._check_method(driver.ComputeDriver.list_instances,
                           "ComputeDriver.list_instances",
                           ['self'])

        self._check_method(driver.ComputeDriver.list_instance_uuids,
                           "ComputeDriver.list_instance_uuids",
                           ['self'])

        self._check_method(driver.ComputeDriver.node_is_available,
                           "ComputeDriver.node_is_available",
                           ['self', 'nodename'])

        self._check_method(driver.ComputeDriver.get_available_nodes,
                           "ComputeDriver.get_available_nodes",
                           ['self', 'refresh'])

        self._check_method(driver.ComputeDriver.get_info,
                           "ComputeDriver.get_info",
                           ['self', 'instance'])

        self._check_method(driver.ComputeDriver.macs_for_instance,
                           "ComputeDriver.macs_for_instance",
                           ['self', 'instance'])

        self._check_method(driver.ComputeDriver.spawn,
                           "ComputeDriver.spawn",
                           ['self', 'context', 'instance', 'image_meta',
                            'injected_files', 'admin_password', 'network_info',
                            'block_device_info'])

        self._check_method(driver.ComputeDriver.destroy,
                           "ComputeDriver.destroy",
                           ['self', 'context', 'instance', 'network_info',
                            'block_device_info', 'destroy_disks',
                            'migrate_data'])

        self._check_method(driver.ComputeDriver.reboot,
                           "ComputeDriver.reboot",
                           ['self', 'context', 'instance', 'network_info',
                            'reboot_type', 'block_device_info',
                            'bad_volumes_callback'])

        self._check_method(driver.ComputeDriver.power_off,
                           "ComputeDriver.power_off",
                           ['self', 'instance'])

        self._check_method(driver.ComputeDriver.power_on,
                           "ComputeDriver.power_on",
                           ['self', 'context', 'instance', 'network_info',
                            'block_device_info'])

        self._check_method(driver.ComputeDriver.get_host_stats,
                           "ComputeDriver.get_host_stats",
                           ['self', 'refresh'])

        self._check_method(driver.ComputeDriver.manage_image_cache,
                           "ComputeDriver.manage_image_cache",
                           ['self', 'context', 'all_instances'])

        self._check_method(driver.ComputeDriver.get_console_output,
                           "ComputeDriver.get_console_output",
                           ['self', 'context', 'instance'])

        self._check_method(driver.ComputeDriver.refresh_security_group_rules,
                           "ComputeDriver.refresh_security_group_rules",
                           ['self', 'security_group_id'])

        self._check_method(driver.ComputeDriver.refresh_security_group_members,
                           "ComputeDriver.refresh_security_group_members",
                           ['self', 'security_group_id'])

        self._check_method(driver.ComputeDriver.refresh_provider_fw_rules,
                           "ComputeDriver.refresh_provider_fw_rules",
                           ['self'])

        self._check_method(
            driver.ComputeDriver.refresh_instance_security_rules,
            "ComputeDriver.refresh_instance_security_rules",
            ['self', 'instance'])

        self._check_method(
            driver.ComputeDriver.ensure_filtering_rules_for_instance,
            "ComputeDriver.ensure_filtering_rules_for_instance",
            ['self', 'instance', 'network_info'])

        self._check_method(driver.ComputeDriver.unfilter_instance,
                           "ComputeDriver.unfilter_instance",
                           ['self', 'instance', 'network_info'])

        self._check_method(driver.ComputeDriver.plug_vifs,
                           "ComputeDriver.plug_vifs",
                           ['self', 'instance', 'network_info'])

        self._check_method(driver.ComputeDriver.unplug_vifs,
                           "ComputeDriver.unplug_vifs",
                           ['self', 'instance', 'network_info'])

        self._check_method(driver.ComputeDriver.rebuild,
                           "ComputeDriver.rebuild",
                           ['self', 'context', 'instance', 'image_meta',
                            'injected_files', 'admin_password', 'bdms',
                            'detach_block_devices', 'attach_block_devices',
                            'network_info', 'recreate', 'block_device_info',
                            'preserve_ephemeral'])
