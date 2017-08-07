# Copyright 2016 IBM Corp.
#
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

import time

import nova.scheduler.utils
import nova.servicegroup
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.unit import cast_as_call
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestServerGet(test.TestCase):
    REQUIRES_LOCKING = True

    def setUp(self):
        super(TestServerGet, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        # The non-admin API client is fine to stay at 2.1 since it just creates
        # and deletes the server.
        self.api = api_fixture.api
        self.admin_api = api_fixture.admin_api
        # The admin API client needs to be at microversion 2.16 to exhibit the
        # regression.
        self.admin_api.microversion = '2.16'

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

        self.start_service('conductor')
        self.flags(driver='chance_scheduler', group='scheduler')
        self.start_service('scheduler')
        self.compute = self.start_service('compute')
        self.consoleauth = self.start_service('consoleauth')

        self.useFixture(cast_as_call.CastAsCall(self))
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def test_list_deleted_instances(self):
        """Regression test for bug #1548980.

        Before fixing this bug, listing deleted instances returned a 404
        because lazy-loading services from a deleted instance failed. Now
        we should be able to list the deleted instance and the host_state
        attribute should be "".
        """
        server = dict(name='server1',
                      imageRef=self.image_id,
                      flavorRef=self.flavor_id)
        server = self.api.post_server({'server': server})
        self.api.delete_server(server['id'])
        # Wait 30 seconds for it to be gone.
        for x in range(30):
            try:
                self.api.get_server(server['id'])
                time.sleep(1)
            except client.OpenStackApiNotFoundException:
                break
        else:
            self.fail('Timed out waiting to delete server: %s' % server['id'])
        servers = self.admin_api.get_servers(search_opts={'deleted': 1})
        self.assertEqual(1, len(servers))
        self.assertEqual(server['id'], servers[0]['id'])
        # host_status is returned in the 2.16 microversion and since the server
        # is deleted it should be the empty string
        self.assertEqual(0, len(servers[0]['host_status']))
