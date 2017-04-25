# Copyright 2013 IBM Corp.
# Copyright 2014 NEC Corporation.  All rights reserved.
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

import webob.exc

from nova.api.openstack.compute import extension_info
from nova.api.openstack import extensions
from nova import exception
from nova import test


class fake_bad_extension(object):
    name = "fake_bad_extension"
    alias = "fake-bad"


class ExtensionLoadingTestCase(test.NoDBTestCase):

    def test_check_bad_extension(self):
        loaded_ext_info = extension_info.LoadedExtensionInfo()
        self.assertFalse(loaded_ext_info._check_extension(fake_bad_extension))

    def test_extensions_expected_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise webob.exc.HTTPNotFound()

        self.assertRaises(webob.exc.HTTPNotFound, fake_func)

    def test_extensions_expected_error_from_list(self):
        @extensions.expected_errors((404, 403))
        def fake_func():
            raise webob.exc.HTTPNotFound()

        self.assertRaises(webob.exc.HTTPNotFound, fake_func)

    def test_extensions_unexpected_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise webob.exc.HTTPConflict()

        self.assertRaises(webob.exc.HTTPInternalServerError, fake_func)

    def test_extensions_unexpected_error_from_list(self):
        @extensions.expected_errors((404, 413))
        def fake_func():
            raise webob.exc.HTTPConflict()

        self.assertRaises(webob.exc.HTTPInternalServerError, fake_func)

    def test_extensions_unexpected_policy_not_authorized_error(self):
        @extensions.expected_errors(404)
        def fake_func():
            raise exception.PolicyNotAuthorized(action="foo")

        self.assertRaises(exception.PolicyNotAuthorized, fake_func)
