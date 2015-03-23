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


class FlavorsSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    sample_dir = 'flavors'
    # TODO(gmann): Overriding '_api_version' till all functional tests
    # are merged between v2 and v2.1. After that base class variable
    # itself can be changed to 'v2'
    _api_version = 'v2'

    def _get_flags(self):
        f = super(FlavorsSampleJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavor_swap.Flavor_swap')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.flavor_disabled.Flavor_disabled')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                      'contrib.flavor_access.Flavor_access')
        f['osapi_compute_extension'].append('nova.api.openstack.compute.'
                       'contrib.flavorextradata.Flavorextradata')
        return f

    def test_flavors_get(self):
        response = self._do_get('flavors/1')
        subs = self._get_regexes()
        self._verify_response('flavor-get-resp', subs, response, 200)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        subs = self._get_regexes()
        self._verify_response('flavors-list-resp', subs, response, 200)

    def test_flavors_detail(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        self._verify_response('flavors-detail-resp', subs, response, 200)
