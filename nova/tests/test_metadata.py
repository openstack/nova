# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for the testing the metadata code."""

import base64
import httplib

import webob

from nova import test
from nova import wsgi
from nova.api.ec2 import metadatarequesthandler
from nova.db.sqlalchemy import api


class MetadataTestCase(test.TestCase):
    """Test that metadata is returning proper values."""

    def setUp(self):
        super(MetadataTestCase, self).setUp()
        self.instance = ({'id': 1,
                         'project_id': 'test',
                         'key_name': None,
                         'host': 'test',
                         'launch_index': 1,
                         'instance_type': 'm1.tiny',
                         'reservation_id': 'r-xxxxxxxx',
                         'user_data': '',
                         'image_ref': 7,
                         'hostname': 'test'})

        def instance_get(*args, **kwargs):
            return self.instance

        def floating_get(*args, **kwargs):
            return '99.99.99.99'

        self.stubs.Set(api, 'instance_get', instance_get)
        self.stubs.Set(api, 'fixed_ip_get_instance', instance_get)
        self.stubs.Set(api, 'instance_get_floating_address', floating_get)
        self.app = metadatarequesthandler.MetadataRequestHandler()

    def request(self, relative_url):
        request = webob.Request.blank(relative_url)
        request.remote_addr = "127.0.0.1"
        return request.get_response(self.app).body

    def test_base(self):
        self.assertEqual(self.request('/'), 'meta-data/\nuser-data')

    def test_user_data(self):
        self.instance['user_data'] = base64.b64encode('happy')
        self.assertEqual(self.request('/user-data'), 'happy')

    def test_security_groups(self):
        def sg_get(*args, **kwargs):
            return [{'name': 'default'}, {'name': 'other'}]
        self.stubs.Set(api, 'security_group_get_by_instance', sg_get)
        self.assertEqual(self.request('/meta-data/security-groups'),
                         'default\nother')
