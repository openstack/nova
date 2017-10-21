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

import datetime

import nova.conf
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client as api_client
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit import policy_fixture

CONF = nova.conf.CONF


class TestServerGet(test.TestCase):

    def setUp(self):
        super(TestServerGet, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))

        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        image_service = fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)

        # NOTE(mriedem): This image has an invalid architecture metadata value
        # and is used for negative testing in the functional stack.
        timestamp = datetime.datetime(2011, 1, 1, 1, 2, 3)
        image = {'id': 'c456eb30-91d7-4f43-8f46-2efd9eccd744',
                 'name': 'fake-image-invalid-arch',
                 'created_at': timestamp,
                 'updated_at': timestamp,
                 'deleted_at': None,
                 'deleted': False,
                 'status': 'active',
                 'is_public': False,
                 'container_format': 'raw',
                 'disk_format': 'raw',
                 'size': '25165824',
                 'properties': {'kernel_id': 'nokernel',
                                'ramdisk_id': 'nokernel',
                                'architecture': 'x64'}}
        self.image_id = image_service.create(None, image)['id']
        self.flavor_id = self.api.get_flavors()[0]['id']

    def test_boot_server_with_invalid_image_meta(self):
        """Regression test for bug #1558866.

        Glance allows you to provide any architecture value for image meta
        properties but nova validates the image metadata against the
        nova.compute.arch.ALL values during the conversion to the ImageMeta
        object. This test ensures we get a 400 back in that case rather than
        a 500.
        """
        server = dict(name='server1',
                      imageRef=self.image_id,
                      flavorRef=self.flavor_id)
        ex = self.assertRaises(api_client.OpenStackApiException,
                               self.api.post_server, {'server': server})
        self.assertEqual(400, ex.response.status_code)
