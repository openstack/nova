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

from nova import exception
from nova.objects import service
from nova.tests import fixtures
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit.api.openstack.compute import test_services
from nova.tests.unit import fake_notifier


class TestServiceNotificationBase(
        notification_sample_base.NotificationSampleTestBase):

    def _verify_notification(self, sample_file_name, replacements=None,
                             actual=None):
        # This just extends the generic _verify_notification to default the
        # service version to the current service version to avoid sample update
        # after every service version bump.
        if 'version' not in replacements:
            replacements['version'] = service.SERVICE_VERSION
        base = super(TestServiceNotificationBase, self)
        base._verify_notification(sample_file_name, replacements, actual)


class TestServiceUpdateNotificationSamplev2_52(TestServiceNotificationBase):

    # These tests have to be capped at 2.52 since the PUT format changes in
    # the 2.53 microversion.
    MAX_MICROVERSION = '2.52'

    def setUp(self):
        super(TestServiceUpdateNotificationSamplev2_52, self).setUp()
        self.stub_out("nova.db.api.service_get_by_host_and_binary",
                      test_services.fake_service_get_by_host_binary)
        self.stub_out("nova.db.api.service_update",
                      test_services.fake_service_update)
        # NOTE(gibi): enable / disable a compute service tries to call
        # the compute service via RPC to update placement. However in these
        # tests the compute services are faked. So stub out the RPC call to
        # avoid waiting for the RPC timeout. The notifications are generated
        # regardless of the result of the RPC call anyhow.
        self.stub_out("nova.compute.rpcapi.ComputeAPI.set_host_enabled",
                      lambda *args, **kwargs: None)
        self.useFixture(utils_fixture.TimeFixture(test_services.fake_utcnow()))
        self.useFixture(fixtures.SingleCellSimple())
        self.service_uuid = test_services.fake_service_get_by_host_binary(
            None, 'host1', 'nova-compute')['uuid']

    def test_service_enable(self):
        body = {'host': 'host1',
                'binary': 'nova-compute'}
        self.admin_api.api_put('os-services/enable', body)
        self._verify_notification('service-update',
                                  replacements={'uuid': self.service_uuid})

    def test_service_disabled(self):
        body = {'host': 'host1',
                'binary': 'nova-compute'}
        self.admin_api.api_put('os-services/disable', body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True,
                                                'uuid': self.service_uuid})

    def test_service_disabled_log_reason(self):
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'disabled_reason': 'test2'}
        self.admin_api.api_put('os-services/disable-log-reason', body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True,
                                                'disabled_reason': 'test2',
                                                'uuid': self.service_uuid})

    def test_service_force_down(self):
        body = {'host': 'host1',
                'binary': 'nova-compute',
                'forced_down': True}
        self.admin_api.api_put('os-services/force-down', body)
        self._verify_notification('service-update',
                                  replacements={'forced_down': True,
                                                'disabled': True,
                                                'disabled_reason': 'test2',
                                                'uuid': self.service_uuid})


class TestServiceUpdateNotificationSampleLatest(
        TestServiceUpdateNotificationSamplev2_52):
    """Tests the PUT /os-services/{service_id} API notifications."""

    MAX_MICROVERSION = 'latest'

    def setUp(self):
        super(TestServiceUpdateNotificationSampleLatest, self).setUp()

        def db_service_get_by_uuid(ctxt, service_uuid):
            for svc in test_services.fake_services_list:
                if svc['uuid'] == service_uuid:
                    return svc
            raise exception.ServiceNotFound(service_id=service_uuid)
        self.stub_out('nova.db.api.service_get_by_uuid',
                      db_service_get_by_uuid)

    def test_service_enable(self):
        body = {'status': 'enabled'}
        self.admin_api.api_put('os-services/%s' % self.service_uuid, body)
        self._verify_notification('service-update',
                                  replacements={'uuid': self.service_uuid})

    def test_service_disabled(self):
        body = {'status': 'disabled'}
        self.admin_api.api_put('os-services/%s' % self.service_uuid, body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True,
                                                'uuid': self.service_uuid})

    def test_service_disabled_log_reason(self):
        body = {'status': 'disabled',
                'disabled_reason': 'test2'}
        self.admin_api.api_put('os-services/%s' % self.service_uuid, body)
        self._verify_notification('service-update',
                                  replacements={'disabled': True,
                                                'disabled_reason': 'test2',
                                                'uuid': self.service_uuid})

    def test_service_force_down(self):
        body = {'forced_down': True}
        self.admin_api.api_put('os-services/%s' % self.service_uuid, body)
        self._verify_notification('service-update',
                                  replacements={'forced_down': True,
                                                'disabled': True,
                                                'disabled_reason': 'test2',
                                                'uuid': self.service_uuid})


class TestServiceNotificationSample(TestServiceNotificationBase):

    def test_service_create(self):
        self.compute2 = self.start_service('compute', host='host2')
        self._verify_notification(
            'service-create',
            replacements={
                'uuid':
                notification_sample_base.NotificationSampleTestBase.ANY})

    def test_service_destroy(self):
        self.compute2 = self.start_service('compute', host='host2')
        # This test runs with the latest microversion by default so we get the
        # service uuid back from the REST API.
        compute2_service_id = self.admin_api.get_services(
            host=self.compute2.host, binary='nova-compute')[0]['id']
        self.admin_api.api_delete('os-services/%s' % compute2_service_id)
        self._verify_notification(
            'service-delete',
            replacements={'uuid': compute2_service_id},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
