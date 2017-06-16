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
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier


class TestKeypairNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def test_keypair_create(self):
        keypair_req = {
            "keypair": {
                "name": "my-key",
                "user_id": "fake",
                "type": "ssh"
        }}
        keypair = self.api.post_keypair(keypair_req)

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'keypair-create-start',
            replacements={},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'keypair-create-end',
            replacements={
                "fingerprint": keypair['fingerprint'],
                "public_key": keypair['public_key']
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
