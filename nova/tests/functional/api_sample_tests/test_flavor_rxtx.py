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

from nova.tests.functional.api_sample_tests import api_sample_base

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class FlavorRxtxJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    extension_name = 'os-flavor-rxtx'

    def _get_flags(self):
        f = super(FlavorRxtxJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavor_rxtx.'
            'Flavor_rxtx')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.'
            'Flavormanage')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavor_disabled.'
            'Flavor_disabled')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavor_access.'
            'Flavor_access')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavorextradata.'
            'Flavorextradata')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavor_swap.'
            'Flavor_swap')
        return f

    def test_flavor_rxtx_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        self._verify_response('flavor-rxtx-get-resp', subs, response, 200)

    def test_flavors_rxtx_detail(self):
        response = self._do_get('flavors/detail')
        self._verify_response('flavor-rxtx-list-resp', {}, response, 200)

    def test_flavors_rxtx_create(self):
        subs = {
            'flavor_id': 100,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavor-rxtx-post-req',
                                 subs)
        self._verify_response('flavor-rxtx-post-resp', subs, response, 200)
