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

import fixtures
import threading
import time

from unittest import mock

from nova import context as nova_context
from nova import objects
from nova.tests.functional.libvirt import base
from nova.virt import libvirt


class TestConcurrentMultiAttachCleanup(base.ServersTestBase):
    """Regression test for bug 2048837.

    This regression test aims to assert that if a multi attached volume is
    attached to two vms on the same host and both are deleted the volume is
    correctly cleaned up.

    Nova historically did not guard the critical section where concurrent
    delete determined if they were the last user of a the host mounted
    multi attach volume. As a result its possible for both delete to believe
    the other would call disconnect and the volume can be leaked.

    see https://bugs.launchpad.net/nova/+bug/2048837 for details

    """

    microversion = 'latest'
    CAST_AS_CALL = False
    REQUIRES_LOCKING = True

    def setUp(self):
        super().setUp()
        self._orgi_should_disconnect = (
            libvirt.LibvirtDriver._should_disconnect_target)
        self.should_disconnect_mock = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._should_disconnect_target',
            mock.Mock(side_effect=self._should_disconnect))).mock
        self.disconnect_volume_mock = self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.volume.volume.'
            'LibvirtFakeVolumeDriver.disconnect_volume',
            mock.Mock())).mock
        self.hostname = self.start_compute()
        self.compute_manager = self.computes[self.hostname]

        self.volume_id = self.cinder.MULTIATTACH_VOL
        # Launch a server and attach a volume
        self.server_a = self._create_server(networks='none')
        self.notifier.wait_for_versioned_notifications('instance.create.end')
        self._attach_volume(self.server_a, self.volume_id)

        # Launch a second server and attempt to attach the same volume again
        self.server_b = self._create_server(networks='none')
        self.notifier.wait_for_versioned_notifications('instance.create.end')
        self._attach_volume(self.server_b, self.volume_id)
        self.lock = threading.Lock()
        # run periodics to allow async tasks to complete
        self._run_periodics()

    def _should_disconnect(self, *args, **kwargs):
        with self.lock:
            result = self._orgi_should_disconnect(
                self.compute_manager.driver, *args, **kwargs)
            return result

    def test_serial_server_delete(self):
        # Now that we have 2 vms both using the same multi attach volume
        # we can delete the volumes serial and confirm that we are cleaning up
        self.should_disconnect_mock.assert_not_called()
        self.disconnect_volume_mock.assert_not_called()

        self._delete_server(self.server_a)
        self.should_disconnect_mock.assert_called()
        self.disconnect_volume_mock.assert_not_called()
        self._delete_server(self.server_b)
        self.disconnect_volume_mock.assert_called()

    def test_concurrent_server_delete(self):
        # Now that we have 2 vms both using the same multi attach volume
        # we can delete the volumes concurrently and confirm that we are
        # cleaning up
        self.should_disconnect_mock.assert_not_called()
        self.disconnect_volume_mock.assert_not_called()
        # emulate concurrent delete
        context = nova_context.get_admin_context()
        servers_this_host = objects.InstanceList.get_uuids_by_host(
                context, self.hostname)
        with mock.patch('nova.objects.InstanceList.get_uuids_by_host',
                        return_value=servers_this_host):
            self.lock.acquire()
            self.api.delete_server(self.server_a['id'])
            self.api.delete_server(self.server_b['id'])
            self.disconnect_volume_mock.assert_not_called()
            # this mostly stabilizes the test but it may not be 100% reliable.
            # locally with time.sleep(1) it passed 42 back to back executions
            # im not sure why this is required given the lock but it is likely
            # due to a the lock being released before a background task is
            # completed. i.e. the conductor or resource trakcer updating state.
            time.sleep(1)
            self.lock.release()
        self._wait_until_deleted(self.server_a)
        self._wait_until_deleted(self.server_b)
        self.should_disconnect_mock.assert_called()
        # Fixme(sean-k-mooney): this is bug 2048837
        try:
            self.disconnect_volume_mock.assert_not_called()
        except AssertionError:
            # NOTE(sean-k-mooney): this reproducer is not 100%
            # reliable so we convert a failure to a skip to avoid
            # gating issues. the bug is addressed in the follow up patch
            # and that test is stable so it is not worth fixing this test
            # beyond the time.sleep(1) above.
            self.skipTest("Bug 2048837: volume disconnect not called")
