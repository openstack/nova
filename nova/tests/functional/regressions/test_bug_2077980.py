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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestImageToLocalBDM(integrated_helpers._IntegratedTestBase):
    """Regression test for bug 2077980

    This regression test asserts the behaviour of server creation requests when
    using a BDM with source_type=image, destination_type=local, and
    boot_index=0, which should result in a failure.
    """
    microversion = 'latest'

    # TODO(stephenfin): We should eventually fail regardless of the value of
    # imageRef, but that requires an API microversion
    def test_image_to_local_bdm__empty_image(self):
        """Assert behaviour when booting with imageRef set to empty string"""
        server = {
            'name': 'test_image_to_local_bdm__null_image',
            'imageRef': '',
            'flavorRef': '1',   # m1.tiny from DefaultFlavorsFixture,
            'networks': 'none',
            'block_device_mapping_v2': [{
                'boot_index': 0,
                'uuid': uuids.image,
                'source_type': 'image',
                'destination_type': 'local'}],
        }
        # NOTE(stephenfin): This should always fail as we don't allow users to
        # set this as it would conflict with the flavor definition.
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.post_server,
            {'server': server})
        self.assertEqual(400, ex.response.status_code)
        self.assertIn("Mapping image to local is not supported.", str(ex))
