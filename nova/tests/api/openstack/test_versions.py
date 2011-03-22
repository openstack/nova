# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import json
import webob

from nova import context
from nova import test
from nova.tests.api.openstack import fakes
from nova.api.openstack import views


class VersionsTest(test.TestCase):
    def setUp(self):
        super(VersionsTest, self).setUp()
        self.context = context.get_admin_context()

    def tearDown(self):
        super(VersionsTest, self).tearDown()

    def test_get_version_list(self):
        req = webob.Request.blank('/')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        versions = json.loads(res.body)["versions"]
        expected = [
            {
                "id": "v1.1",
                "status": "CURRENT",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.1",
                    }
                ],
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v1.0",
                    }
                ],
            },
        ]
        self.assertEqual(versions, expected)

    def test_view_builder(self):
        base_url = "http://example.org/"

        version_data = {
            "id": "3.2.1",
            "status": "CURRENT",
        }

        expected = {
            "id": "3.2.1",
            "status": "CURRENT",
            "links": [
                {
                    "rel": "self",
                    "href": "http://example.org/3.2.1",
                },
            ],
        }

        builder = views.versions.ViewBuilder(base_url)
        output = builder.build(version_data)

        self.assertEqual(output, expected)

    def test_generate_href(self):
        base_url = "http://example.org/app/"
        version_number = "v1.4.6"

        expected = "http://example.org/app/v1.4.6"

        builder = views.versions.ViewBuilder(base_url)
        actual = builder.generate_href(version_number)

        self.assertEqual(actual, expected)
