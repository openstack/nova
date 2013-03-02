# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Openstack Foundation
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Tests for the deprecated network API."""

import inspect

from nova.network import api
from nova.network import api_deprecated
from nova import test

# NOTE(jkoelker) These tests require that decorators in the apis
#                "do the right thing" and set __name__ properly
#                they should all be using functools.wraps or similar
#                functionality.


def isapimethod(obj):
    if inspect.ismethod(obj) and not obj.__name__.startswith('_'):
        return True
    return False


def discover_real_method(name, method):
    if method.func_closure:
        for closure in method.func_closure:
            if closure.cell_contents.__name__ == name:
                return closure.cell_contents
    return method


class DeprecatedApiTestCase(test.TestCase):
    def setUp(self):
        super(DeprecatedApiTestCase, self).setUp()
        self.api = api.API()
        self.api_deprecated = api_deprecated.API()

        self.api_methods = inspect.getmembers(self.api, isapimethod)

    def test_api_compat(self):
        methods = [m[0] for m in self.api_methods]
        deprecated_methods = [getattr(self.api_deprecated, n, None)
                              for n in methods]
        missing = [m[0] for m in zip(methods, deprecated_methods)
                   if m[1] is None]

        self.assertFalse(missing,
                         'Deprecated api needs methods: %s' % missing)

    def test_method_signatures(self):
        for name, method in self.api_methods:
            deprecated_method = getattr(self.api_deprecated, name, None)
            self.assertIsNotNone(deprecated_method,
                                 'Deprecated api has no method %s' % name)

            method = discover_real_method(name, method)
            deprecated_method = discover_real_method(name,
                                                     deprecated_method)

            api_argspec = inspect.getargspec(method)
            deprecated_argspec = inspect.getargspec(deprecated_method)

            # NOTE/TODO(jkoelker) Should probably handle the case where
            #                     varargs/keywords are used.
            self.assertEqual(api_argspec.args, deprecated_argspec.args,
                             "API method %s arguments differ" % name)
