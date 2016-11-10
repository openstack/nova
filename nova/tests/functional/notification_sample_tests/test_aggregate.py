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


class TestAggregateNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def test_aggregate_create_delete(self):
        aggregate_req = {
            "aggregate": {
                "name": "my-aggregate",
                "availability_zone": "nova"}}
        aggregate = self.admin_api.post_aggregate(aggregate_req)

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-create-start',
            replacements={
                'uuid': aggregate['uuid']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'aggregate-create-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        self.admin_api.delete_aggregate(aggregate['id'])

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-delete-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'aggregate-delete-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def test_aggregate_add_remove_host(self):
        aggregate_req = {
            "aggregate": {
                "name": "my-aggregate",
                "availability_zone": "nova"}}
        aggregate = self.admin_api.post_aggregate(aggregate_req)

        fake_notifier.reset()

        add_host_req = {
            "add_host": {
                "host": "compute"
            }
        }
        self.admin_api.post_aggregate_action(aggregate['id'], add_host_req)

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-add_host-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'aggregate-add_host-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        remove_host_req = {
            "remove_host": {
                "host": "compute"
            }
        }
        self.admin_api.post_aggregate_action(aggregate['id'], remove_host_req)

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-remove_host-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'aggregate-remove_host-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

        self.admin_api.delete_aggregate(aggregate['id'])
