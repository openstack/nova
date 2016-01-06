# Copyright 2012 Nebula, Inc.
# Copyright 2014 IBM Corp.
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

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class MultipleCreateJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-multiple-create"

    def _get_flags(self):
        f = super(MultipleCreateJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.multiple_create.'
            'Multiple_create')
        return f

    def test_multiple_create(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'compute_endpoint': self._get_compute_endpoint(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-post-req', subs)
        self._verify_response('multiple-create-post-resp', subs, response, 202)

    def test_multiple_create_without_reservation_id(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'compute_endpoint': self._get_compute_endpoint(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-no-resv-post-req',
                                  subs)
        self._verify_response('multiple-create-no-resv-post-resp', subs,
                              response, 202)
