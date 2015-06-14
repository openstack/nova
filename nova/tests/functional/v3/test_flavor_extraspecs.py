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

from oslo_config import cfg

from nova.tests.functional.v3 import api_sample_base

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')


class FlavorExtraSpecsSampleJsonTests(api_sample_base.ApiSampleTestBaseV3):
    ADMIN_API = True
    extension_name = 'flavor-extra-specs'
    # TODO(park): Overriding '_api_version' till all functional tests
    # are merged between v2 and v2.1. After that base class variable
    # itself can be changed to 'v2'
    _api_version = 'v2'

    def _get_flags(self):
        f = super(FlavorExtraSpecsSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavorextraspecs.'
            'Flavorextraspecs')
        return f

    def _flavor_extra_specs_create(self):
        subs = {'value1': 'value1',
                'value2': 'value2'
        }
        response = self._do_post('flavors/1/os-extra_specs',
                                 'flavor-extra-specs-create-req', subs)
        self._verify_response('flavor-extra-specs-create-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_get(self):
        subs = {'value1': 'value1'}
        self._flavor_extra_specs_create()
        response = self._do_get('flavors/1/os-extra_specs/key1')
        self._verify_response('flavor-extra-specs-get-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_list(self):
        subs = {'value1': 'value1',
                'value2': 'value2'
        }
        self._flavor_extra_specs_create()
        response = self._do_get('flavors/1/os-extra_specs')
        self._verify_response('flavor-extra-specs-list-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_create(self):
        self._flavor_extra_specs_create()

    def test_flavor_extra_specs_update(self):
        subs = {'value1': 'new_value1'}
        self._flavor_extra_specs_create()
        response = self._do_put('flavors/1/os-extra_specs/key1',
                                'flavor-extra-specs-update-req', subs)
        self._verify_response('flavor-extra-specs-update-resp',
                              subs, response, 200)

    def test_flavor_extra_specs_delete(self):
        self._flavor_extra_specs_create()
        response = self._do_delete('flavors/1/os-extra_specs/key1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, '')
