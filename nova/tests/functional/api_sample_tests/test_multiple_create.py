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

from nova.tests.functional.api_sample_tests import test_servers


class MultipleCreateJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-multiple-create"

    def test_multiple_create(self):
        subs = {
            'image_id': self.glance.auto_disk_config_enabled_image['id'],
            'compute_endpoint': self._get_compute_endpoint(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-post-req', subs)
        self._verify_response('multiple-create-post-resp', subs, response, 202)

    def test_multiple_create_without_reservation_id(self):
        subs = {
            'image_id': self.glance.auto_disk_config_enabled_image['id'],
            'compute_endpoint': self._get_compute_endpoint(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-no-resv-post-req',
                                  subs)
        self._verify_response('multiple-create-no-resv-post-resp', subs,
                              response, 202)
