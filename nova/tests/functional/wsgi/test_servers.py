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
import six

from nova.compute import api as compute_api
from nova.policies import base as base_policies
from nova.policies import servers as servers_policies
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class ServersPreSchedulingTestCase(test.TestCase,
                                   integrated_helpers.InstanceHelperMixin):
    """Tests for the servers API with unscheduled instances.

    With cellsv2 an instance is not written to an instance table in the cell
    database until it has been scheduled to a cell. This means we need to be
    careful to ensure the instance can still be represented before that point.

    NOTE(alaski): The above is the desired future state, this test class is
    here to confirm that the behavior does not change as the transition is
    made.

    This test class starts the wsgi stack for the nova api service, and uses
    an in memory database for persistence. It does not allow requests to get
    past scheduling.
    """
    api_major_version = 'v2.1'

    def setUp(self):
        super(ServersPreSchedulingTestCase, self).setUp()
        fake_image.stub_out_image_service(self)
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NoopConductorFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(nova_fixtures.PlacementFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api
        self.api.microversion = 'latest'
        self.useFixture(nova_fixtures.SingleCellSimple(
            instances_created=False))

    def test_instance_from_buildrequest(self):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
            }
        }
        create_resp = self.api.api_post('servers', body)
        get_resp = self.api.api_get('servers/%s' %
                                    create_resp.body['server']['id'])
        flavor_get_resp = self.api.api_get('flavors/%s' %
                                           body['server']['flavorRef'])

        server = get_resp.body['server']
        # Validate a few things
        self.assertEqual('foo', server['name'])
        self.assertEqual(image_ref, server['image']['id'])
        self.assertEqual(flavor_get_resp.body['flavor']['name'],
                         server['flavor']['original_name'])
        self.assertEqual('', server['hostId'])
        self.assertIsNone(server['OS-SRV-USG:launched_at'])
        self.assertIsNone(server['OS-SRV-USG:terminated_at'])
        self.assertFalse(server['locked'])
        self.assertEqual([], server['tags'])
        self.assertEqual('scheduling', server['OS-EXT-STS:task_state'])
        self.assertEqual('building', server['OS-EXT-STS:vm_state'])
        self.assertEqual('BUILD', server['status'])

    def test_instance_from_buildrequest_old_service(self):
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
            }
        }
        create_resp = self.api.api_post('servers', body)
        get_resp = self.api.api_get('servers/%s' %
                                    create_resp.body['server']['id'])
        flavor_get_resp = self.api.api_get('flavors/%s' %
                                           body['server']['flavorRef'])
        server = get_resp.body['server']
        # Just validate some basics
        self.assertEqual('foo', server['name'])
        self.assertEqual(image_ref, server['image']['id'])
        self.assertEqual(flavor_get_resp.body['flavor']['name'],
                         server['flavor']['original_name'])
        self.assertEqual('', server['hostId'])
        self.assertIsNone(server['OS-SRV-USG:launched_at'])
        self.assertIsNone(server['OS-SRV-USG:terminated_at'])
        self.assertFalse(server['locked'])
        self.assertEqual([], server['tags'])
        self.assertEqual('scheduling', server['OS-EXT-STS:task_state'])
        self.assertEqual('building', server['OS-EXT-STS:vm_state'])
        self.assertEqual('BUILD', server['status'])

    def test_delete_instance_from_buildrequest(self):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
            }
        }
        create_resp = self.api.api_post('servers', body)
        self.api.api_delete('servers/%s' % create_resp.body['server']['id'])
        get_resp = self.api.api_get('servers/%s' %
                                    create_resp.body['server']['id'],
                                    check_response_status=False)
        self.assertEqual(404, get_resp.status)

    def test_delete_instance_from_buildrequest_old_service(self):
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
            }
        }
        create_resp = self.api.api_post('servers', body)
        self.api.api_delete('servers/%s' % create_resp.body['server']['id'])
        get_resp = self.api.api_get('servers/%s' %
                                    create_resp.body['server']['id'],
                                    check_response_status=False)
        self.assertEqual(404, get_resp.status)

    def _test_instance_list_from_buildrequests(self):
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
            }
        }
        inst1 = self.api.api_post('servers', body)
        body['server']['name'] = 'bar'
        inst2 = self.api.api_post('servers', body)

        list_resp = self.api.get_servers()
        # Default sort is created_at desc, so last created is first
        self.assertEqual(2, len(list_resp))
        self.assertEqual(inst2.body['server']['id'], list_resp[0]['id'])
        self.assertEqual('bar', list_resp[0]['name'])
        self.assertEqual(inst1.body['server']['id'], list_resp[1]['id'])
        self.assertEqual('foo', list_resp[1]['name'])

        # Change the sort order
        list_resp = self.api.api_get(
            'servers/detail?sort_key=created_at&sort_dir=asc')
        list_resp = list_resp.body['servers']
        self.assertEqual(2, len(list_resp))
        self.assertEqual(inst1.body['server']['id'], list_resp[0]['id'])
        self.assertEqual('foo', list_resp[0]['name'])
        self.assertEqual(inst2.body['server']['id'], list_resp[1]['id'])
        self.assertEqual('bar', list_resp[1]['name'])

    def test_instance_list_from_buildrequests(self):
        self.useFixture(nova_fixtures.AllServicesCurrent())
        self._test_instance_list_from_buildrequests()

    def test_instance_list_from_buildrequests_old_service(self):
        self._test_instance_list_from_buildrequests()

    def test_instance_list_from_buildrequests_with_tags(self):
        """Creates two servers with two tags each, where the 2nd tag (tag2)
        is the only intersection between the tags in both servers. This is
        used to test the various tags filters working in the BuildRequestList.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        image_ref = fake_image.get_valid_image_id()
        body = {
            'server': {
                'name': 'foo',
                'imageRef': image_ref,
                'flavorRef': '1',
                'networks': 'none',
                'tags': ['tag1', 'tag2']
            }
        }
        inst1 = self.api.api_post('servers', body)
        body['server']['name'] = 'bar'
        body['server']['tags'] = ['tag2', 'tag3']
        inst2 = self.api.api_post('servers', body)

        # list servers using tags=tag1,tag2
        list_resp = self.api.api_get(
            'servers/detail?tags=tag1,tag2')
        list_resp = list_resp.body['servers']
        self.assertEqual(1, len(list_resp))
        self.assertEqual(inst1.body['server']['id'], list_resp[0]['id'])
        self.assertEqual('foo', list_resp[0]['name'])

        # list servers using tags-any=tag1,tag3
        list_resp = self.api.api_get(
            'servers/detail?tags-any=tag1,tag3')
        list_resp = list_resp.body['servers']
        self.assertEqual(2, len(list_resp))
        # Default sort is created_at desc, so last created is first
        self.assertEqual(inst2.body['server']['id'], list_resp[0]['id'])
        self.assertEqual('bar', list_resp[0]['name'])
        self.assertEqual(inst1.body['server']['id'], list_resp[1]['id'])
        self.assertEqual('foo', list_resp[1]['name'])

        # list servers using not-tags=tag1,tag2
        list_resp = self.api.api_get(
            'servers/detail?not-tags=tag1,tag2')
        list_resp = list_resp.body['servers']
        self.assertEqual(1, len(list_resp))
        self.assertEqual(inst2.body['server']['id'], list_resp[0]['id'])
        self.assertEqual('bar', list_resp[0]['name'])

        # list servers using not-tags-any=tag1,tag3
        list_resp = self.api.api_get(
            'servers/detail?not-tags-any=tag1,tag3')
        list_resp = list_resp.body['servers']
        self.assertEqual(0, len(list_resp))

    @mock.patch('nova.objects.service.get_minimum_version_all_cells',
                return_value=compute_api.BFV_RESERVE_MIN_COMPUTE_VERSION)
    def test_bfv_delete_build_request_pre_scheduling_ocata(self, mock_get):
        cinder = self.useFixture(nova_fixtures.CinderFixture(self))

        volume_id = nova_fixtures.CinderFixture.IMAGE_BACKED_VOL
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'test_bfv_delete_build_request_pre_scheduling',
                'networks': 'none',
                'block_device_mapping_v2': [
                    {
                        'boot_index': 0,
                        'uuid': volume_id,
                        'source_type': 'volume',
                        'destination_type': 'volume'
                    },
                ]
            }
        })

        # Since _IntegratedTestBase uses the CastAsCall fixture, when we
        # get the server back we know all of the volume stuff should be done.
        self.assertIn(volume_id, cinder.reserved_volumes)

        # Now delete the server, which should go through the "local delete"
        # code in the API, find the build request and delete it along with
        # detaching the volume from the instance.
        self.api.delete_server(server['id'])

        # The volume should no longer have any attachments as instance delete
        # should have removed them.
        self.assertNotIn(volume_id, cinder.reserved_volumes)

    def test_bfv_delete_build_request_pre_scheduling(self):
        cinder = self.useFixture(
            nova_fixtures.CinderFixtureNewAttachFlow(self))
        # This makes the get_minimum_version_all_cells check say we're running
        # the latest of everything.
        self.useFixture(nova_fixtures.AllServicesCurrent())

        volume_id = nova_fixtures.CinderFixtureNewAttachFlow.IMAGE_BACKED_VOL
        server = self.api.post_server({
            'server': {
                'flavorRef': '1',
                'name': 'test_bfv_delete_build_request_pre_scheduling',
                'networks': 'none',
                'block_device_mapping_v2': [
                    {
                        'boot_index': 0,
                        'uuid': volume_id,
                        'source_type': 'volume',
                        'destination_type': 'volume'
                    },
                ]
            }
        })

        # Since _IntegratedTestBase uses the CastAsCall fixture, when we
        # get the server back we know all of the volume stuff should be done.
        self.assertIn(volume_id,
                      cinder.volume_ids_for_instance(server['id']))

        # Now delete the server, which should go through the "local delete"
        # code in the API, find the build request and delete it along with
        # detaching the volume from the instance.
        self.api.delete_server(server['id'])

        # The volume should no longer have any attachments as instance delete
        # should have removed them.
        self.assertNotIn(volume_id,
                         cinder.volume_ids_for_instance(server['id']))

    def test_instance_list_build_request_marker_ip_filter(self):
        """Tests listing instances with a marker that is in the build_requests
        table and also filtering by ip, in which case the ip filter can't
        possibly find anything because instances that are not yet scheduled
        can't have ips, but the point is to find the marker in the build
        requests table.
        """
        self.useFixture(nova_fixtures.AllServicesCurrent())
        # Create the server.
        body = {
            'server': {
                'name': 'test_instance_list_build_request_marker_ip_filter',
                'imageRef': fake_image.get_valid_image_id(),
                'flavorRef': '1',
                'networks': 'none'
            }
        }
        server = self.api.post_server(body)
        # Now list servers using the one we just created as the marker and
        # include the ip filter (see bug 1764685).
        search_opts = {
            'marker': server['id'],
            'ip': '192.168.159.150'
        }
        servers = self.api.get_servers(search_opts=search_opts)
        # We'll get 0 servers back because there are none with the specified
        # ip filter.
        self.assertEqual(0, len(servers))


class EnforceVolumeBackedForZeroDiskFlavorTestCase(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Tests for the os_compute_api:servers:create:zero_disk_flavor policy rule

    These tests explicitly rely on microversion 2.1.
    """

    def setUp(self):
        super(EnforceVolumeBackedForZeroDiskFlavorTestCase, self).setUp()
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.policy_fixture = (
            self.useFixture(policy_fixture.RealPolicyFixture()))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        # We need a zero disk flavor for the tests in this class.
        flavor_req = {
            "flavor": {
                "name": "zero-disk-flavor",
                "ram": 1024,
                "vcpus": 2,
                "disk": 0
            }
        }
        self.zero_disk_flavor = self.admin_api.post_flavor(flavor_req)

    def test_create_image_backed_server_with_zero_disk_fails(self):
        """Tests that a non-admin trying to create an image-backed server
        using a flavor with 0 disk will result in a 403 error when rule
        os_compute_api:servers:create:zero_disk_flavor is set to admin-only.
        """
        self.policy_fixture.set_rules({
            servers_policies.ZERO_DISK_FLAVOR: base_policies.RULE_ADMIN_API},
            overwrite=False)
        server_req = self._build_minimal_create_server_request(
            self.api,
            'test_create_image_backed_server_with_zero_disk_fails',
            fake_image.AUTO_DISK_CONFIG_ENABLED_IMAGE_UUID,
            self.zero_disk_flavor['id'])
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server, {'server': server_req})
        self.assertIn('Only volume-backed servers are allowed for flavors '
                      'with zero disk.', six.text_type(ex))
        self.assertEqual(403, ex.response.status_code)

    def test_create_volume_backed_server_with_zero_disk_allowed(self):
        """Tests that creating a volume-backed server with a zero-root
        disk flavor will be allowed for admins.
        """
        # For this test, we want to start conductor and the scheduler but
        # we don't start compute so that scheduling fails; we don't really
        # care about successfully building an active server here.
        self.useFixture(nova_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.CinderFixture(self))
        self.start_service('conductor')
        self.start_service('scheduler')
        server_req = self._build_minimal_create_server_request(
            self.api,
            'test_create_volume_backed_server_with_zero_disk_allowed',
            flavor_id=self.zero_disk_flavor['id'])
        server_req.pop('imageRef', None)
        server_req['block_device_mapping_v2'] = [{
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL,
            'source_type': 'volume',
            'destination_type': 'volume',
            'boot_index': 0
        }]
        server = self.admin_api.post_server({'server': server_req})
        server = self._wait_for_state_change(self.api, server, 'ERROR')
        self.assertIn('No valid host', server['fault']['message'])
