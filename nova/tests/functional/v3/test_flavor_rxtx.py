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

from nova.tests.functional.v3 import api_sample_base


class FlavorRxtxJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = 'os-flavor-rxtx'

    def test_flavor_rxtx_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        subs.update(self._get_regexes())
        self._verify_response('flavor-rxtx-get-resp', subs, response, 200)

    def test_flavors_rxtx_detail(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavor-rxtx-list-resp', subs, response, 200)

    def test_flavors_rxtx_create(self):
        subs = {
            'flavor_id': 100,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavor-rxtx-post-req',
                                 subs)
        subs.update(self._get_regexes())
        self._verify_response('flavor-rxtx-post-resp', subs, response, 200)
