# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova import test
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional.libvirt import test_vgpu


class VGPUTestsListDevices(test_vgpu.VGPUTestBase):
    """Regression test for bug 2098892.

    Test that nodeDeviceLookupByName() is called with valid types to prevent:

    File "/usr/lib64/python3.9/site-packages/libvirt.py", line 5201, in
      nodeDeviceLookupByName ret =
      libvirtmod.virNodeDeviceLookupByName(self._o, name)
      TypeError: virNodeDeviceLookupByName() argument 2 must be str or None,
      not Proxy

    in the future. This test relies on the LibvirtFixture checking for the
    correct types in its nodeDeviceLookupByName() method and raising TypeError
    if they are invalid.

    We don't test this by importing the libvirt module because the libvirt
    module is forbidden to be imported into our test environment. It is
    excluded from test-requirements.txt and we also use the
    ImportModulePoisonFixture in nova/test.py to prevent use of modules such as
    libvirt.
    """

    def setUp(self):
        super().setUp()

        # Start compute supporting only nvidia-11
        self.flags(
            enabled_mdev_types=fakelibvirt.NVIDIA_11_VGPU_TYPE,
            group='devices')

        self.start_compute_with_vgpu('host1')

        def fake_nodeDeviceLookupByName(self, name):
            # See bug https://bugs.launchpad.net/nova/+bug/2098892
            # We don't test this by importing the libvirt module because the
            # libvirt module is forbidden to be imported into our test
            # environment.  It is excluded from test-requirements.txt and we
            # also use the ImportModulePoisonFixture in nova/test.py to prevent
            # use of modules such as libvirt.
            if not isinstance(name, str) and name is not None:
                raise TypeError(
                    'virNodeDeviceLookupByName() argument 2 must be str or '
                    f'None, not {type(name)}')

        # FIXME(melwitt): We need to patch this only for this test because if
        # we add it to the LibvirtFixture right away, it will cause the
        # following additional tests to fail:
        #
        # nova.tests.functional.libvirt.test_reshape.VGPUReshapeTests
        #   test_create_servers_with_vgpu
        #
        # nova.tests.functional.libvirt.test_vgpu.DifferentMdevClassesTests
        #   test_create_servers_with_different_mdev_classes
        #   test_resize_servers_with_mlx5
        #
        # nova.tests.functional.libvirt.test_vgpu.VGPULimitMultipleTypesTests
        #   test_create_servers_with_vgpu
        #
        # nova.tests.functional.libvirt.test_vgpu.VGPULiveMigrationTests
        #   test_live_migrate_server
        #   test_live_migration_fails_on_old_source
        #   test_live_migration_fails_due_to_non_supported_mdev_types
        #   test_live_migration_fails_on_old_destination
        #
        # nova.tests.functional.libvirt.
        #                           test_vgpu.VGPULiveMigrationTestsLMFailed
        #   test_live_migrate_server
        #   test_live_migration_fails_on_old_source
        #   test_live_migration_fails_due_to_non_supported_mdev_types
        #   test_live_migration_fails_on_old_destination
        #
        # nova.tests.functional.libvirt.test_vgpu.VGPUMultipleTypesTests
        #   test_create_servers_with_specific_type
        #   test_create_servers_with_vgpu
        #
        # nova.tests.functional.libvirt.test_vgpu.VGPUTests
        #   test_multiple_instance_create
        #   test_create_servers_with_vgpu
        #   test_create_server_with_two_vgpus_isolated
        #   test_resize_servers_with_vgpu
        #
        # nova.tests.functional.libvirt.test_vgpu.VGPUTestsLibvirt7_3
        #   test_create_servers_with_vgpu
        #   test_create_server_with_two_vgpus_isolated
        #   test_resize_servers_with_vgpu
        #   test_multiple_instance_create
        #
        # nova.tests.functional.regressions.
        #                               test_bug_1951656.VGPUTestsLibvirt7_7
        #   test_create_servers_with_vgpu
        self.stub_out(
            'nova.tests.fixtures.libvirt.Connection.nodeDeviceLookupByName',
            fake_nodeDeviceLookupByName)

    def test_update_available_resource(self):
        # We only want to verify no errors were logged by
        # update_available_resource (logging under the 'except Exception:').
        # FIXME(melwitt): This currently will log an error and traceback
        # because of the bug. Update this when the bug is fixed.
        e = self.assertRaises(
            test.TestingException, self._run_periodics, raise_on_error=True)
        self.assertIn('TypeError', str(e))
