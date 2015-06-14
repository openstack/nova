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


class QuotaClassesSampleJsonTests(api_sample_base.ApiSampleTestBaseV3):
    ADMIN_API = True
    extension_name = "os-quota-class-sets"
    set_id = 'test_class'
    # TODO(Park): Overriding '_api_version' till all functional tests
    # are merged between v2 and v2.1. After that base class variable
    # itself can be changed to 'v2'
    _api_version = 'v2'

    def _get_flags(self):
        f = super(QuotaClassesSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.quota_classes.'
                      'Quota_classes')
        return f

    def test_show_quota_classes(self):
        # Get api sample to show quota classes.
        response = self._do_get('os-quota-class-sets/%s' % self.set_id)
        subs = {'set_id': self.set_id}
        self._verify_response('quota-classes-show-get-resp', subs,
                              response, 200)

    def test_update_quota_classes(self):
        # Get api sample to update quota classes.
        response = self._do_put('os-quota-class-sets/%s' % self.set_id,
                                'quota-classes-update-post-req',
                                {})
        self._verify_response('quota-classes-update-post-resp',
                              {}, response, 200)
