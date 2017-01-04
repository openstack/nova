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
from nova.tests.functional.api import client as api_client
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier


class TestExceptionNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def test_versioned_exception_notification_with_correct_params(
            self):

        post = {
            "aggregate": {
                "name": "versioned_exc_aggregate",
                "availability_zone": "nova"
            }
        }

        self.admin_api.api_post('os-aggregates', post)
        # recreating the aggregate raises exception
        self.assertRaises(api_client.OpenStackApiException,
                          self.admin_api.api_post, 'os-aggregates', post)

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'compute-exception',
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])
