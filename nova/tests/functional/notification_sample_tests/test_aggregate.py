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

    def setUp(self):
        self.flags(compute_driver='fake.FakeDriverWithCaching')
        super(TestAggregateNotificationSample, self).setUp()

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

    def test_aggregate_update_metadata(self):
        aggregate_req = {
            "aggregate": {
                "name": "my-aggregate",
                "availability_zone": "nova"}}
        aggregate = self.admin_api.post_aggregate(aggregate_req)

        set_metadata_req = {
            "set_metadata": {
                "metadata": {
                    "availability_zone": "AZ-1"
                }
            }
        }
        fake_notifier.reset()
        self.admin_api.post_aggregate_action(aggregate['id'], set_metadata_req)

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-update_metadata-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'aggregate-update_metadata-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def test_aggregate_updateprops(self):
        aggregate_req = {
            "aggregate": {
                "name": "my-aggregate",
                "availability_zone": "nova"}}
        aggregate = self.admin_api.post_aggregate(aggregate_req)

        update_req = {
            "aggregate": {
                "name": "my-new-aggregate"}}
        self.admin_api.put_aggregate(aggregate['id'], update_req)

        # 0. aggregate-create-start
        # 1. aggregate-create-end
        # 2. aggregate-update_prop-start
        # 3. aggregate-update_prop-end
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'aggregate-update_prop-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'aggregate-update_prop-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
                actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def test_aggregate_cache_images(self):
        aggregate_req = {
            "aggregate": {
                "name": "my-aggregate",
                "availability_zone": "nova"}}
        aggregate = self.admin_api.post_aggregate(aggregate_req)
        add_host_req = {
            "add_host": {
                "host": "compute"
            }
        }
        self.admin_api.post_aggregate_action(aggregate['id'], add_host_req)

        fake_notifier.reset()

        cache_images_req = {
            'cache': [
                {'id': '155d900f-4e14-4e4c-a73d-069cbf4541e6'}
            ]
        }
        self.admin_api.api_post('/os-aggregates/%s/images' % aggregate['id'],
                                cache_images_req)
        # Since the operation is asynchronous we have to wait for the end
        # notification.
        fake_notifier.wait_for_versioned_notifications(
            'aggregate.cache_images.end')

        self.assertEqual(3, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                         fake_notifier.VERSIONED_NOTIFICATIONS)
        self._verify_notification(
            'aggregate-cache_images-start',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'aggregate-cache_images-progress',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self._verify_notification(
            'aggregate-cache_images-end',
            replacements={
                'uuid': aggregate['uuid'],
                'id': aggregate['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
