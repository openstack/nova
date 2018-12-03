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

from nova.compute import utils as compute_utils
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import policy_fixture


class BootFromVolumeOverQuotaRaceDeleteTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Test for regression bug 1806064 introduced in Pike.

    This is very similar to regression bug 1404867 where reserved/attached
    volumes during a boot from volume request are not detached while deleting
    a server that failed to schedule.

    In this case, scheduling is successful but the late quota check in
    ComputeTaskManager.schedule_and_build_instances fails. In the case of a
    scheduling failure, the instance record along with the associated BDMs
    are created in the cell0 database and that is where the "local delete"
    code in the API finds them to detach the related volumes. In the case of
    the quota fail race, the instance has already been created in a selected
    cell but the BDMs records have not been and are thus not "seen" during
    the API local delete and the volumes are left attached to a deleted server.

    An additional issue, covered in the test here, is that tags provided when
    creating the server are not retrievable from the API after the late quota
    check fails.
    """

    def setUp(self):
        super(BootFromVolumeOverQuotaRaceDeleteTest, self).setUp()
        # We need the cinder fixture for boot from volume testing.
        self.cinder_fixture = self.useFixture(
            nova_fixtures.CinderFixtureNewAttachFlow(self))
        # Use the standard fixtures.
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).api
        # Use microversion 2.52 which allows creating a server with tags.
        self.api.microversion = '2.52'

        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')

    def test_bfv_quota_race_local_delete(self):
        # Setup a boot-from-volume request where the API will create a
        # volume attachment record for the given pre-existing volume.
        # We also tag the server since tags, like BDMs, should be created in
        # the cell database along with the instance.
        volume_id = nova_fixtures.CinderFixtureNewAttachFlow.IMAGE_BACKED_VOL
        server = {
            'server': {
                'name': 'test_bfv_quota_race_local_delete',
                'flavorRef': self.api.get_flavors()[0]['id'],
                'imageRef': '',
                'block_device_mapping_v2': [{
                    'boot_index': 0,
                    'source_type': 'volume',
                    'destination_type': 'volume',
                    'uuid': volume_id
                }],
                'networks': 'auto',
                'tags': ['bfv']
            }
        }

        # Now we need to stub out the quota check routine so that we can
        # simulate the race where the initial quota check in the API passes
        # but fails in conductor once the instance has been created in cell1.
        original_quota_check = compute_utils.check_num_instances_quota

        def stub_check_num_instances_quota(_self, context, instance_type,
                                           min_count, *args, **kwargs):
            # Determine where we are in the flow based on whether or not the
            # min_count is 0 (API will pass 1, conductor will pass 0).
            if min_count == 0:
                raise exception.TooManyInstances(
                    'test_bfv_quota_race_local_delete')
            # We're checking from the API so perform the original quota check.
            return original_quota_check(
                _self, context, instance_type, min_count, *args, **kwargs)

        self.stub_out('nova.compute.utils.check_num_instances_quota',
                      stub_check_num_instances_quota)

        server = self.api.post_server(server)
        server = self._wait_for_state_change(self.api, server, 'ERROR')
        # At this point, the build request should be gone and the instance
        # should have been created in cell1.
        context = nova_context.get_admin_context()
        self.assertRaises(exception.BuildRequestNotFound,
                          objects.BuildRequest.get_by_instance_uuid,
                          context, server['id'])
        # The default cell in the functional tests is cell1 but we want to
        # specifically target cell1 to make sure the instance exists there
        # and we're not just getting lucky somehow due to the fixture.
        cell1 = self.cell_mappings[test.CELL1_NAME]
        with nova_context.target_cell(context, cell1) as cctxt:
            # This would raise InstanceNotFound if the instance isn't in cell1.
            instance = objects.Instance.get_by_uuid(cctxt, server['id'])
            self.assertIsNone(instance.host, 'instance.host should not be set')
            # Make sure the BDMs and tags also exist in cell1.
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                cctxt, instance.uuid)
            self.assertEqual(1, len(bdms), 'BDMs were not created in cell1')
            tags = objects.TagList.get_by_resource_id(cctxt, instance.uuid)
            self.assertEqual(1, len(tags), 'Tags were not created in cell1')

        # Make sure we can still view the tags on the server before it is
        # deleted.
        self.assertEqual(['bfv'], server['tags'])

        # Now delete the server which, since it does not have a host, will be
        # deleted "locally" from the API.
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)

        # The volume should have been detached by the API.
        attached_volumes = self.cinder_fixture.volume_ids_for_instance(
            server['id'])
        # volume_ids_for_instance is a generator so listify
        self.assertEqual(0, len(list(attached_volumes)))
