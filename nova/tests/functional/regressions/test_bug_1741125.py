# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from nova.compute import manager as compute_manager
from nova.tests.functional import integrated_helpers


class TestServerResizeReschedule(integrated_helpers.ProviderUsageBaseTestCase):
    """Regression test for bug #1741125

    During testing in the alternate host series, it was found that retries
    when resizing an instance would always fail. This turned out to be true
    even before alternate hosts for resize was introduced. Further
    investigation showed that there was a race in call to retry the resize
    and the revert of the original attempt.

    This adds a functional regression test to show the failure. A follow up
    patch with the fix will modify the test to show it passing again.
    """

    compute_driver = 'fake.SmallFakeDriver'

    def setUp(self):
        super(TestServerResizeReschedule, self).setUp()
        self.compute1 = self._start_compute(host='host1')
        self.compute2 = self._start_compute(host='host2')
        self.compute3 = self._start_compute(host='host3')
        self.compute4 = self._start_compute(host='host4')

        flavors = self.api.get_flavors()
        self.flavor1 = flavors[0]
        self.flavor2 = flavors[1]
        if self.flavor1["disk"] > self.flavor2["disk"]:
            # Make sure that flavor1 is smaller
            self.flavor1, self.flavor2 = self.flavor2, self.flavor1

    def test_resize_reschedule_uses_host_lists(self):
        """Test that when a resize attempt fails, the retry comes from the
        supplied host_list, and does not call the scheduler.
        """
        server_req = self._build_minimal_create_server_request(
                self.api, 'some-server', flavor_id=self.flavor1['id'],
                image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
                networks='none')

        self.first_attempt = True
        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(self.api, created_server,
                'ACTIVE')

        actual_prep_resize = compute_manager.ComputeManager._prep_resize

        def fake_prep_resize(*args, **kwargs):
            if self.first_attempt:
                # Only fail the first time
                self.first_attempt = False
                raise Exception('fake_prep_resize')
            actual_prep_resize(*args, **kwargs)

        # Yes this isn't great in a functional test, but it's simple.
        self.stub_out('nova.compute.manager.ComputeManager._prep_resize',
                      fake_prep_resize)

        server_uuid = server["id"]
        data = {"resize": {"flavorRef": self.flavor2['id']}}
        self.api.post_server_action(server_uuid, data)

        server = self._wait_for_state_change(self.api, created_server,
                'VERIFY_RESIZE')
        self.assertEqual(self.flavor2['name'],
                         server['flavor']['original_name'])


class TestServerResizeRescheduleWithCachingScheduler(
        TestServerResizeReschedule):
    """Tests the reschedule scenario using the CachingScheduler."""

    def setUp(self):
        self.flags(driver='caching_scheduler', group='scheduler')
        super(TestServerResizeRescheduleWithCachingScheduler, self).setUp()
