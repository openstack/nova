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


class TestServerGroupNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def test_server_group_create_delete(self):
        group_req = {
            "name": "test-server-group",
            "policies": ["anti-affinity"]}
        group = self.api.post_server_groups(group_req)

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'server_group-create',
            replacements={'uuid': group['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])

        fake_notifier.reset()
        self.api.delete_server_group(group['id'])

        self.assertEqual(1, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'server_group-delete',
            replacements={'uuid': group['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
