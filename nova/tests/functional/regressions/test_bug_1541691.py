# Copyright 2016 HPE, Inc.
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

import nova.scheduler.utils
import nova.servicegroup
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture


class TestServerValidation(test.TestCase):
    REQUIRES_LOCKING = True
    microversion = None

    def setUp(self):
        super(TestServerValidation, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)
        self.addCleanup(nova.tests.unit.image.fake.FakeImageService_reset)

        self.api = api_fixture.api
        self.image_id = self.api.get_images()[0]['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def test_name_validation(self):
        """Regression test for bug #1541691.

        The current jsonschema validation spits a giant wall of regex
        at you (about 500k characters). This is not useful to
        determine why your request actually failed.

        Ensure that once we fix this it doesn't regress.
        """
        server = dict(name='server1 ',
                      imageRef=self.image_id,
                      flavorRef=self.flavor_id)

        server_args = {'server': server}
        self.assertRaises(client.OpenStackApiException, self.api.post_server,
                          server_args)
