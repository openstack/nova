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
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ImageSizeSampleJsonTests(api_sample_base.ApiSampleTestBaseV21):
    extension_name = "image-size"
    extra_extensions_to_load = ["images", "image-metadata"]

    def _get_flags(self):
        f = super(ImageSizeSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.image_size.Image_size')
        return f

    def test_show(self):
        # Get api sample of one single image details request.
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-get-resp', subs, response, 200)

    def test_detail(self):
        # Get api sample of all images details request.
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        self._verify_response('images-details-get-resp', subs, response, 200)
