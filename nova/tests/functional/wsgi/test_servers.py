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

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture


class ServersPreSchedulingTestCase(test.TestCase):
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

        server = get_resp.body['server']
        # Validate a few things
        self.assertEqual('foo', server['name'])
        self.assertEqual(image_ref, server['image']['id'])
        self.assertEqual('1', server['flavor']['id'])
        self.assertEqual('', server['hostId'])
        self.assertIsNone(None, server['OS-SRV-USG:launched_at'])
        self.assertIsNone(None, server['OS-SRV-USG:terminated_at'])
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
        server = get_resp.body['server']
        # Just validate some basics
        self.assertEqual('foo', server['name'])
        self.assertEqual(image_ref, server['image']['id'])
        self.assertEqual('1', server['flavor']['id'])
        self.assertEqual('', server['hostId'])
        self.assertIsNone(None, server['OS-SRV-USG:launched_at'])
        self.assertIsNone(None, server['OS-SRV-USG:terminated_at'])
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
