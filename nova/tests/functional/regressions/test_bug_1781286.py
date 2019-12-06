# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures
import mock
from oslo_db import exception as oslo_db_exc

from nova.compute import manager as compute_manager
from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class RescheduleBuildAvailabilityZoneUpCall(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """This is a regression test for bug 1781286 which was introduced with
    a change in Pike to set the instance availability_zone in conductor
    once a host is selected from the scheduler. The regression in the initial
    server build case is when a reschedule is triggered, and the cell conductor
    does not have access to the API DB, it fails with a CantStartEngineError
    trying to connect to the API DB to get availability zone (aggregate) info
    about the alternate host selection.
    """
    def setUp(self):
        super(RescheduleBuildAvailabilityZoneUpCall, self).setUp()
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start controller services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.start_service('conductor')
        self.start_service('scheduler')
        # Start two computes with the fake reschedule driver.
        self.flags(compute_driver='fake.FakeRescheduleDriver')
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')
        # Listen for notifications.
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

    def test_server_create_reschedule_blocked_az_up_call(self):
        self.flags(default_availability_zone='us-central')
        # We need to stub out the call to get_host_availability_zone to blow
        # up once we have gone to the compute service. With the way our
        # RPC/DB fixtures are setup it's non-trivial to try and separate a
        # superconductor from a cell conductor so we can configure the cell
        # conductor from not having access to the API DB but that would be a
        # a nice thing to have at some point.
        original_bari = compute_manager.ComputeManager.build_and_run_instance

        def wrap_bari(*args, **kwargs):
            # Poison the AZ query to blow up as if the cell conductor does not
            # have access to the API DB.
            self.useFixture(
                fixtures.MockPatch(
                    'nova.objects.AggregateList.get_by_host',
                    side_effect=oslo_db_exc.CantStartEngineError))
            return original_bari(*args, **kwargs)

        self.stub_out('nova.compute.manager.ComputeManager.'
                      'build_and_run_instance', wrap_bari)
        server = self._build_server()
        server = self.api.post_server({'server': server})
        # Because we poisoned AggregateList.get_by_host after hitting the
        # compute service we have to wait for the notification that the build
        # is complete and then stop the mock so we can use the API again.
        fake_notifier.wait_for_versioned_notifications('instance.create.end')
        # Note that we use stopall here because we actually called
        # build_and_run_instance twice so we have more than one instance of
        # the mock that needs to be stopped.
        mock.patch.stopall()
        server = self._wait_for_state_change(server, 'ACTIVE')
        # We should have rescheduled and the instance AZ should be set from the
        # Selection object. Since neither compute host is in an AZ, the server
        # is in the default AZ from config.
        self.assertEqual('us-central', server['OS-EXT-AZ:availability_zone'])


class RescheduleMigrateAvailabilityZoneUpCall(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """This is a regression test for the resize/cold migrate aspect of
    bug 1781286 where the cell conductor does not have access to the API DB.
    """
    def setUp(self):
        super(RescheduleMigrateAvailabilityZoneUpCall, self).setUp()
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        # Start controller services.
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.start_service('conductor')
        self.start_service('scheduler')
        # We need three hosts for this test, one is the initial host on which
        # the server is built, and the others are for the migration where the
        # first will fail and the second is an alternate.
        self.start_service('compute', host='host1')
        self.start_service('compute', host='host2')
        self.start_service('compute', host='host3')
        # Listen for notifications.
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)

    def test_migrate_reschedule_blocked_az_up_call(self):
        self.flags(default_availability_zone='us-central')
        # We need to stub out the call to get_host_availability_zone to blow
        # up once we have gone to the compute service.
        original_prep_resize = compute_manager.ComputeManager._prep_resize
        self.rescheduled = None

        def wrap_prep_resize(_self, *args, **kwargs):
            # Poison the AZ query to blow up as if the cell conductor does not
            # have access to the API DB.
            self.agg_mock = self.useFixture(
                fixtures.MockPatch(
                    'nova.objects.AggregateList.get_by_host',
                    side_effect=oslo_db_exc.CantStartEngineError)).mock
            if self.rescheduled is None:
                # Track the first host that we rescheduled from.
                self.rescheduled = _self.host
                # Trigger a reschedule.
                raise exception.ComputeResourcesUnavailable(
                    reason='test_migrate_reschedule_blocked_az_up_call')
            return original_prep_resize(_self, *args, **kwargs)

        self.stub_out('nova.compute.manager.ComputeManager._prep_resize',
                      wrap_prep_resize)
        server = self._build_server()
        server = self.api.post_server({'server': server})
        server = self._wait_for_state_change(server, 'ACTIVE')
        original_host = server['OS-EXT-SRV-ATTR:host']

        # Now cold migrate the server to the other host.
        self.api.post_server_action(server['id'], {'migrate': None})
        # Because we poisoned AggregateList.get_by_host after hitting the
        # compute service we have to wait for the notification that the resize
        # is complete and then stop the mock so we can use the API again.
        fake_notifier.wait_for_versioned_notifications(
            'instance.resize_finish.end')
        # Note that we use stopall here because we actually called _prep_resize
        # twice so we have more than one instance of the mock that needs to be
        # stopped.
        mock.patch.stopall()
        server = self._wait_for_state_change(server, 'VERIFY_RESIZE')
        final_host = server['OS-EXT-SRV-ATTR:host']
        self.assertNotIn(final_host, [original_host, self.rescheduled])
        # We should have rescheduled and the instance AZ should be set from the
        # Selection object. Since neither compute host is in an AZ, the server
        # is in the default AZ from config.
        self.assertEqual('us-central', server['OS-EXT-AZ:availability_zone'])
        self.agg_mock.assert_not_called()
