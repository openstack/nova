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

    def test_keypair_create_delete(self):
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

        self.api.delete_keypair(keypair['name'])
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'keypair-delete-start',
            replacements={
                "fingerprint": keypair['fingerprint'],
                "public_key": keypair['public_key']
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'keypair-delete-end',
            replacements={
                "fingerprint": keypair['fingerprint'],
                "public_key": keypair['public_key']
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def test_keypair_import(self):
        pub_key = ('ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDx8nkQv/zgGg'
                   'B4rMYmIf+6A4l6Rr+o/6lHBQdW5aYd44bd8JttDCE/F/pNRr0l'
                   'RE+PiqSPO8nDPHw0010JeMH9gYgnnFlyY3/OcJ02RhIPyyxYpv'
                   '9FhY+2YiUkpwFOcLImyrxEsYXpD/0d3ac30bNH6Sw9JD9UZHYc'
                   'pSxsIbECHw== Generated-by-Nova')
        keypair_req = {
            "keypair": {
                "name": "my-key",
                "user_id": "fake",
                "public_key": pub_key,
                "type": "ssh"}}

        self.api.post_keypair(keypair_req)

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'keypair-import-start',
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'keypair-import-end',
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
