# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from nova.tests.functional.api_sample_tests import api_sample_base


class FlavorManageSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = 'flavor-manage'

    def _create_flavor(self):
        """Create a flavor."""
        subs = {
            'flavor_id': '10',
            'flavor_name': "test_flavor"
        }
        response = self._do_post("flavors",
                                 "flavor-create-post-req",
                                 subs)
        self._verify_response("flavor-create-post-resp", subs, response, 200)

    def test_create_delete_flavor(self):
        # Get api sample to create and delete a flavor.
        self._create_flavor()
        response = self._do_delete("flavors/10")
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)


class FlavorManageSampleJsonTests2_55(FlavorManageSampleJsonTests):
    microversion = '2.55'
    scenarios = [('v2_55', {'api_major_version': 'v2.1'})]

    def test_update_flavor_description(self):
        response = self._do_put("flavors/1", "flavor-update-req", {})
        self._verify_response("flavor-update-resp", {}, response, 200)


class FlavorManageSampleJsonTests2_75(FlavorManageSampleJsonTests2_55):
    microversion = '2.75'
    scenarios = [('v2_75', {'api_major_version': 'v2.1'})]
