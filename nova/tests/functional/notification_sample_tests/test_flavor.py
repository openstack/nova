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


class TestFlavorNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def test_flavor_create(self):
        body = {
            "flavor": {
                "name": "test_flavor",
                "ram": 1024,
                "vcpus": 2,
                "disk": 10,
                "id": "a22d5517-147c-4147-a0d1-e698df5cd4e3",
                "rxtx_factor": 2.0
            }
        }
        self.admin_api.api_post('flavors', body)
        self._verify_notification('flavor-create')

    def test_flavor_destroy(self):
        body = {
            "flavor": {
                "name": "test_flavor",
                "ram": 1024,
                "vcpus": 2,
                "disk": 10,
                "id": "a22d5517-147c-4147-a0d1-e698df5cd4e3",
                "rxtx_factor": 2.0
            }
        }
        # Create a flavor.
        self.admin_api.api_post('flavors', body)
        self.admin_api.api_delete(
            'flavors/a22d5517-147c-4147-a0d1-e698df5cd4e3')
        self._verify_notification(
            'flavor-delete', actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def test_flavor_update(self):
        body = {
            "flavor": {
                "name": "test_flavor",
                "ram": 1024,
                "vcpus": 2,
                "disk": 10,
                "id": "a22d5517-147c-4147-a0d1-e698df5cd4e3",
                "os-flavor-access:is_public": False,
                "rxtx_factor": 2.0
            }
        }
        # Create a flavor.
        self.admin_api.api_post('flavors', body)

        body = {
            "extra_specs": {
                "key1": "value1",
                "key2": "value2"
            }
        }
        self.admin_api.api_post(
            'flavors/a22d5517-147c-4147-a0d1-e698df5cd4e3/os-extra_specs',
            body)

        body = {
            "addTenantAccess": {
                "tenant": "fake_tenant"
            }
        }
        self.admin_api.api_post(
            'flavors/a22d5517-147c-4147-a0d1-e698df5cd4e3/action',
            body)

        self._verify_notification(
            'flavor-update', actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
