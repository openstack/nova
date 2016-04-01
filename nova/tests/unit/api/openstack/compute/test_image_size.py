# Copyright 2013 Rackspace Hosting
# All Rights Reserved.
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

from oslo_serialization import jsonutils
import webob

from nova.image import glance
from nova import test
from nova.tests.unit.api.openstack import fakes

NOW_API_FORMAT = "2010-10-11T10:30:22Z"
IMAGES = [{
        'id': '123',
        'name': 'public image',
        'metadata': {'key1': 'value1'},
        'updated': NOW_API_FORMAT,
        'created': NOW_API_FORMAT,
        'status': 'ACTIVE',
        'progress': 100,
        'minDisk': 10,
        'minRam': 128,
        'size': 12345678,
        "links": [{
            "rel": "self",
            "href": "http://localhost/v2/fake/images/123",
        },
        {
            "rel": "bookmark",
            "href": "http://localhost/fake/images/123",
        }],
    },
    {
        'id': '124',
        'name': 'queued snapshot',
        'updated': NOW_API_FORMAT,
        'created': NOW_API_FORMAT,
        'status': 'SAVING',
        'progress': 25,
        'minDisk': 0,
        'minRam': 0,
        'size': 87654321,
        "links": [{
            "rel": "self",
            "href": "http://localhost/v2/fake/images/124",
        },
        {
            "rel": "bookmark",
            "href": "http://localhost/fake/images/124",
        }],
    }]


def fake_show(*args, **kwargs):
    return IMAGES[0]


def fake_detail(*args, **kwargs):
    return IMAGES


class ImageSizeTestV21(test.NoDBTestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-IMG-SIZE'

    def setUp(self):
        super(ImageSizeTestV21, self).setUp()
        self.stubs.Set(glance.GlanceImageService, 'show', fake_show)
        self.stubs.Set(glance.GlanceImageService, 'detail', fake_detail)
        self.flags(osapi_compute_extension=['nova.api.openstack.compute'
                                            '.contrib.image_size.Image_size'])
        self.flags(api_servers=['http://localhost:9292'], group='glance')

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(self._get_app())
        return res

    def _get_app(self):
        return fakes.wsgi_app_v21(init_only=('images', 'image-size'))

    def _get_image(self, body):
        return jsonutils.loads(body).get('image')

    def _get_images(self, body):
        return jsonutils.loads(body).get('images')

    def assertImageSize(self, image, size):
        self.assertEqual(image.get('%s:size' % self.prefix), size)

    def test_show(self):
        url = '/v2/fake/images/1'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        image = self._get_image(res.body)
        self.assertImageSize(image, 12345678)

    def test_detail(self):
        url = '/v2/fake/images/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        images = self._get_images(res.body)
        self.assertImageSize(images[0], 12345678)
        self.assertImageSize(images[1], 87654321)


class ImageSizeTestV2(ImageSizeTestV21):
    def _get_app(self):
        return fakes.wsgi_app(init_only=('images',))
