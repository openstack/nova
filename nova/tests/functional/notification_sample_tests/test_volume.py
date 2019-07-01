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

from nova import context
from nova.tests import fixtures
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier


class TestVolumeUsageNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(use_neutron=True)
        self.flags(volume_usage_poll_interval=60)
        super(TestVolumeUsageNotificationSample, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixture(self)
        self.useFixture(self.cinder)

    def _setup_server_with_volume_attached(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        fake_notifier.reset()

        return server

    def test_volume_usage_with_detaching_volume(self):
        server = self._setup_server_with_volume_attached()
        self.api.delete_server_volume(server['id'],
                                      self.cinder.SWAP_OLD_VOL)
        self._wait_for_notification('instance.volume_detach.end')

        # 0. volume_detach-start
        # 1. volume.usage
        # 2. volume_detach-end
        self.assertEqual(3, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'volume-usage',
            replacements={'instance_uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def test_instance_poll_volume_usage(self):
        server = self._setup_server_with_volume_attached()

        self.compute.manager._poll_volume_usage(context.get_admin_context())

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'volume-usage',
            replacements={'instance_uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
