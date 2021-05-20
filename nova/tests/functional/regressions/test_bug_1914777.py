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

import mock

from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers


class TestDeleteWhileBooting(test.TestCase,
                             integrated_helpers.InstanceHelperMixin):
    """This tests race scenarios where an instance is deleted while booting.

    In these scenarios, the nova-api service is racing with nova-conductor
    service; nova-conductor is in the middle of booting the instance when
    nova-api begins fulfillment of a delete request. As the two services
    delete records out from under each other, both services need to handle
    it properly such that a delete request will always be fulfilled.

    Another scenario where two requests can race and delete things out from
    under each other is if two or more delete requests are racing while the
    instance is booting.

    In order to force things into states where bugs have occurred, we must
    mock some object retrievals from the database to simulate the different
    points at which a delete request races with a create request or another
    delete request. We aim to mock only the bare minimum necessary to recreate
    the bug scenarios.
    """
    def setUp(self):
        super(TestDeleteWhileBooting, self).setUp()
        self.useFixture(nova_fixtures.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.GlanceFixture(self))

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.api

        self.ctxt = nova_context.get_context()

        # We intentionally do not start a conductor or scheduler service, since
        # our goal is to simulate an instance that has not been scheduled yet.

        # Kick off a server create request and move on once it's in the BUILD
        # state. Since we have no conductor or scheduler service running, the
        # server will "hang" in an unscheduled state for testing.
        self.server = self._create_server(expected_state='BUILD')
        # Simulate that a different request has deleted the build request
        # record after this delete request has begun processing. (The first
        # lookup of the build request occurs in the servers API to get the
        # instance object in order to delete it).
        # We need to get the build request now before we mock the method.
        self.br = objects.BuildRequest.get_by_instance_uuid(
            self.ctxt, self.server['id'])

    @mock.patch('nova.objects.build_request.BuildRequest.get_by_instance_uuid')
    def test_build_request_and_instance_not_found(self, mock_get_br):
        """This tests a scenario where another request has deleted the build
        request record and the instance record ahead of us.
        """
        # The first lookup at the beginning of the delete request in the
        # ServersController succeeds and the second lookup to handle "delete
        # while booting" in compute/api fails after a different request has
        # deleted it.
        br_not_found = exception.BuildRequestNotFound(uuid=self.server['id'])
        mock_get_br.side_effect = [self.br, br_not_found, br_not_found]
        self._delete_server(self.server)

    @mock.patch('nova.objects.build_request.BuildRequest.get_by_instance_uuid')
    @mock.patch('nova.objects.InstanceMapping.get_by_instance_uuid')
    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    def test_deleting_instance_at_the_same_time(self, mock_get_i, mock_get_im,
                                                mock_get_br):
        """This tests the scenario where another request is trying to delete
        the instance record at the same time we are, while the instance is
        booting. An example of this: while the create and delete are running at
        the same time, the delete request deletes the build request, the create
        request finds the build request already deleted when it tries to delete
        it. The create request deletes the instance record and then delete
        request tries to lookup the instance after it deletes the build
        request. Its attempt to lookup the instance fails because the create
        request already deleted it.
        """
        # First lookup at the beginning of the delete request in the
        # ServersController succeeds, second lookup to handle "delete while
        # booting" in compute/api fails after the conductor has deleted it.
        br_not_found = exception.BuildRequestNotFound(uuid=self.server['id'])
        mock_get_br.side_effect = [self.br, br_not_found]
        # Simulate the instance transitioning from having no cell assigned to
        # having a cell assigned while the delete request is being processed.
        # First lookup of the instance mapping has the instance unmapped (no
        # cell) and subsequent lookups have the instance mapped to cell1.
        no_cell_im = objects.InstanceMapping(
            context=self.ctxt, instance_uuid=self.server['id'],
            cell_mapping=None)
        has_cell_im = objects.InstanceMapping(
            context=self.ctxt, instance_uuid=self.server['id'],
            cell_mapping=self.cell_mappings['cell1'])
        mock_get_im.side_effect = [
            no_cell_im, has_cell_im, has_cell_im, has_cell_im, has_cell_im]
        # Simulate that the instance object has been created by the conductor
        # in the create path while the delete request is being processed.
        # First lookups are before the instance has been deleted and the last
        # lookup is after the conductor has deleted the instance. Use the build
        # request to make an instance object for testing.
        i = self.br.get_new_instance(self.ctxt)
        i_not_found = exception.InstanceNotFound(instance_id=self.server['id'])
        mock_get_i.side_effect = [i, i, i, i_not_found, i_not_found]

        # Simulate that the conductor is running instance_destroy at the same
        # time as we are.
        def fake_instance_destroy(*args, **kwargs):
            # NOTE(melwitt): This is a misleading exception, as it is not only
            # raised when a constraint on 'host' is not met, but also when two
            # instance_destroy calls are racing. In this test, the soft delete
            # returns 0 rows affected because another request soft deleted the
            # record first.
            raise exception.ObjectActionError(
                action='destroy', reason='host changed')

        self.stub_out(
            'nova.objects.instance.Instance.destroy', fake_instance_destroy)
        self._delete_server(self.server)
