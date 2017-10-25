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

from nova import context as nova_context
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base


class FlavorsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = 'flavors'
    flavor_show_id = '1'
    subs = {}

    def test_flavors_get(self):
        response = self._do_get('flavors/%s' % self.flavor_show_id)
        self._verify_response('flavor-get-resp', self.subs, response, 200)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        self._verify_response('flavors-list-resp', self.subs, response, 200)

    def test_flavors_detail(self):
        response = self._do_get('flavors/detail')
        self._verify_response('flavors-detail-resp', self.subs, response,
                              200)


class FlavorsSampleJsonTest2_55(FlavorsSampleJsonTest):
    microversion = '2.55'
    scenarios = [('v2_55', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(FlavorsSampleJsonTest2_55, self).setUp()
        # Get the existing flavors created by DefaultFlavorsFixture.
        ctxt = nova_context.get_admin_context()
        flavors = objects.FlavorList.get_all(ctxt)
        # Flavors are sorted by flavorid in ascending order by default, so
        # get the last flavor in the list and create a new flavor with an
        # incremental flavorid so we have a predictable sort order for the
        # sample response.
        new_flavor_id = int(flavors[-1].flavorid) + 1
        new_flavor = objects.Flavor(
            ctxt, memory_mb=2048, vcpus=1, root_gb=20, flavorid=new_flavor_id,
            name='m1.small.description', description='test description')
        new_flavor.create()
        self.flavor_show_id = new_flavor_id
        self.subs = {'flavorid': new_flavor_id}
