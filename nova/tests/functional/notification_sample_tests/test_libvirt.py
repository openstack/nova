#    Copyright 2018 NTT Corporation
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

import fixtures
import mock

import nova.conf
from nova import exception
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import host


CONF = nova.conf.CONF


class TestLibvirtErrorNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(compute_driver='libvirt.LibvirtDriver')
        self.useFixture(fakelibvirt.FakeLibvirtFixture())
        self.useFixture(fixtures.MockPatchObject(host.Host, 'initialize'))
        super(TestLibvirtErrorNotificationSample, self).setUp()

    @mock.patch('nova.virt.libvirt.host.Host._get_connection')
    def test_libvirt_connect_error(self, mock_get_conn):
        mock_get_conn.side_effect = fakelibvirt.libvirtError(
            'Sample exception for versioned notification test.')
        # restart the compute service
        self.assertRaises(exception.HypervisorUnavailable,
                          self.restart_compute_service, self.compute)

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'libvirt-connect-error',
            replacements={
                'ip': CONF.my_ip,
                'reason.function_name': self.ANY,
                'reason.module_name': self.ANY,
                'reason.traceback': self.ANY
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
