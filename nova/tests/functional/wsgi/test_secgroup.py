# Copyright 2015 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log as logging
import testscenarios

from nova import test
from nova.tests import fixtures as nova_fixtures
import nova.tests.unit.image.fake
from nova.tests.unit import policy_fixture

LOG = logging.getLogger(__name__)


# TODO(stephenfin): Add InstanceHelperMixin
class SecgroupsFullstack(testscenarios.WithScenarios, test.TestCase):
    """Tests for security groups

    TODO: describe security group API

    TODO: define scope

    """
    REQUIRES_LOCKING = True
    _image_ref_parameter = 'imageRef'
    _flavor_ref_parameter = 'flavorRef'

    # This test uses ``testscenarios`` which matrix multiplies the
    # test across the scenarios listed below setting the attributes
    # in the dictionary on ``self`` for each scenario.
    scenarios = [
        ('v2', {
            'api_major_version': 'v2'}),
        # test v2.1 base microversion
        ('v2_1', {
            'api_major_version': 'v2.1'}),
    ]

    def setUp(self):
        super(SecgroupsFullstack, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture())

        self.api = api_fixture.api

        # the image fake backend needed for image discovery
        nova.tests.unit.image.fake.stub_out_image_service(self)

    # TODO(sdague): refactor this method into the API client, we're
    # going to use it a lot
    def _build_minimal_create_server_request(self, name):
        server = {}

        image = self.api.get_images()[0]
        LOG.info("Image: %s", image)

        if self._image_ref_parameter in image:
            image_href = image[self._image_ref_parameter]
        else:
            image_href = image['id']
            image_href = 'http://fake.server/%s' % image_href

        # We now have a valid imageId
        server[self._image_ref_parameter] = image_href

        # Set a valid flavorId
        flavor = self.api.get_flavors()[1]
        server[self._flavor_ref_parameter] = ('http://fake.server/%s'
                                              % flavor['id'])
        server['name'] = name
        return server

    def test_security_group_fuzz(self):
        """Test security group doesn't explode with a 500 on bad input.

        Originally reported with bug
        https://bugs.launchpad.net/nova/+bug/1239723

        """
        server = self._build_minimal_create_server_request("sg-fuzz")
        # security groups must be passed as a list, this is an invalid
        # format. The jsonschema in v2.1 caught it automatically, but
        # in v2 we used to throw a 500.
        server['security_groups'] = {"name": "sec"}
        resp = self.api.api_post('/servers', {'server': server},
                                 check_response_status=False)
        self.assertEqual(400, resp.status)
