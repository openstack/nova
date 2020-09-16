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


class ImagesSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = 'images'

    def test_images_list(self):
        # Get api sample of images get list request.
        response = self._do_get('images')
        self._verify_response('images-list-get-resp', {}, response, 200)

    def test_image_get(self):
        # Get api sample of one single image details request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        response = self._do_get('images/%s' % image_id)
        subs = {'image_id': image_id}
        self._verify_response('image-get-resp', subs, response, 200)

    def test_images_details(self):
        # Get api sample of all images details request.
        response = self._do_get('images/detail')
        self._verify_response('images-details-get-resp', {}, response, 200)

    def test_image_metadata_get(self):
        # Get api sample of an image metadata request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        response = self._do_get('images/%s/metadata' % image_id)
        subs = {'image_id': image_id}
        self._verify_response('image-metadata-get-resp', subs, response, 200)

    def test_image_metadata_post(self):
        # Get api sample to update metadata of an image metadata request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        response = self._do_post(
                'images/%s/metadata' % image_id,
                'image-metadata-post-req', {})
        self._verify_response('image-metadata-post-resp', {}, response, 200)

    def test_image_metadata_put(self):
        # Get api sample of image metadata put request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        response = self._do_put('images/%s/metadata' %
                                (image_id), 'image-metadata-put-req', {})
        self._verify_response('image-metadata-put-resp', {}, response, 200)

    def test_image_meta_key_get(self):
        # Get api sample of an image metadata key request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        key = "kernel_id"
        response = self._do_get('images/%s/metadata/%s' % (image_id, key))
        self._verify_response('image-meta-key-get', {}, response, 200)

    def test_image_meta_key_put(self):
        # Get api sample of image metadata key put request.
        image_id = self.glance.auto_disk_config_enabled_image['id']
        key = "auto_disk_config"
        response = self._do_put('images/%s/metadata/%s' % (image_id, key),
                                'image-meta-key-put-req', {})
        self._verify_response('image-meta-key-put-resp', {}, response, 200)
