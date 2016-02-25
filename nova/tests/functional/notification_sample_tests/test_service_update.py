# All Rights Reserved.
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

from oslo_utils import fixture as utils_fixture

from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit.api.openstack.compute import test_services


class TestServiceUpdateNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        super(TestServiceUpdateNotificationSample, self).setUp()
        self.stub_out("nova.db.service_get_by_host_and_binary",
                      test_services.fake_service_get_by_host_binary)
        self.stub_out("nova.db.service_update",
                      test_services.fake_service_update)
        self.useFixture(utils_fixture.TimeFixture(test_services.fake_utcnow()))

    def test_service_enable(self):
        body = {'host': 'host1',
                'binary': 'nova-compute'}
        self.admin_api.api_put('os-services/enable', body)
        self._verify_notification('service-update')

    def test_service_disabled(self):
        body = {'host': 'host1',
                'binary': 'nova-compute'}
        self.admin_api.api_put('os-services/disable', body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True})

    def test_service_disabled_log_reason(self):
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'disabled_reason': 'test2'}
        self.admin_api.api_put('os-services/disable-log-reason', body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True,
                                                'disabled_reason': 'test2'})

    def test_service_force_down(self):
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'forced_down': True}
        self.admin_api.microversion = '2.12'
        self.admin_api.api_put('os-services/force-down', body)
        self._verify_notification('service-update',
                                  replacements={'forced_down': True,
                                                'disabled': True,
                                                'disabled_reason': 'test2'})
