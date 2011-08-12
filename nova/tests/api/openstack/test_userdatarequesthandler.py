# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import base64
import json
import unittest
import webob

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import test
from nova import log as logging

from nova.tests.api.openstack import fakes

LOG = logging.getLogger('nova.api.openstack.userdata')

USER_DATA_STRING = ("This is an encoded string")
ENCODE_STRING = base64.b64encode(USER_DATA_STRING)


def return_server_by_address(context, address):
    instance = {"user_data": ENCODE_STRING}
    instance["fixed_ips"] = {"address": address,
                             "floating_ips": []}
    return instance


def return_non_existing_server_by_address(context, address):
    raise exception.NotFound()


class TestUserdatarequesthandler(test.TestCase):

    def setUp(self):
        super(TestUserdatarequesthandler, self).setUp()
        self.stubs.Set(db, 'instance_get_by_fixed_ip',
                return_server_by_address)

    def test_user_data(self):
        req = webob.Request.blank('/latest/user-data')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.body, USER_DATA_STRING)

    def test_user_data_non_existing_fixed_address(self):
        self.stubs.Set(db, 'instance_get_by_fixed_ip',
                return_non_existing_server_by_address)
        self.flags(use_forwarded_for=False)
        req = webob.Request.blank('/latest/user-data')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_user_data_invalid_url(self):
        req = webob.Request.blank('/latest/user-data-invalid')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 404)

    def test_user_data_with_use_forwarded_header(self):
        self.flags(use_forwarded_for=True)
        req = webob.Request.blank('/latest/user-data')
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 200)
        self.assertEqual(res.body, USER_DATA_STRING)
