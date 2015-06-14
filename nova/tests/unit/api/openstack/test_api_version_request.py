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

from nova.api.openstack import api_version_request
from nova import exception
from nova import test


class APIVersionRequestTests(test.NoDBTestCase):
    def test_valid_version_strings(self):
        def _test_string(version, exp_major, exp_minor):
            v = api_version_request.APIVersionRequest(version)
            self.assertEqual(v.ver_major, exp_major)
            self.assertEqual(v.ver_minor, exp_minor)

        _test_string("1.1", 1, 1)
        _test_string("2.10", 2, 10)
        _test_string("5.234", 5, 234)
        _test_string("12.5", 12, 5)
        _test_string("2.0", 2, 0)
        _test_string("2.200", 2, 200)

    def test_null_version(self):
        v = api_version_request.APIVersionRequest()
        self.assertTrue(v.is_null())

    def test_invalid_version_strings(self):
        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "2")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "200")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "2.1.4")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "200.23.66.3")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "5 .3")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "5. 3")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "5.03")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "02.1")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "2.001")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, " 2.1")

        self.assertRaises(exception.InvalidAPIVersionString,
                          api_version_request.APIVersionRequest, "2.1 ")

    def test_version_comparisons(self):
        v1 = api_version_request.APIVersionRequest("2.0")
        v2 = api_version_request.APIVersionRequest("2.5")
        v3 = api_version_request.APIVersionRequest("5.23")
        v4 = api_version_request.APIVersionRequest("2.0")
        v_null = api_version_request.APIVersionRequest()

        self.assertTrue(v1 < v2)
        self.assertTrue(v3 > v2)
        self.assertTrue(v1 != v2)
        self.assertTrue(v1 == v4)
        self.assertTrue(v1 != v_null)
        self.assertTrue(v_null == v_null)
        self.assertRaises(TypeError, v1.__cmp__, "2.1")

    def test_version_matches(self):
        v1 = api_version_request.APIVersionRequest("2.0")
        v2 = api_version_request.APIVersionRequest("2.5")
        v3 = api_version_request.APIVersionRequest("2.45")
        v4 = api_version_request.APIVersionRequest("3.3")
        v5 = api_version_request.APIVersionRequest("3.23")
        v6 = api_version_request.APIVersionRequest("2.0")
        v7 = api_version_request.APIVersionRequest("3.3")
        v8 = api_version_request.APIVersionRequest("4.0")
        v_null = api_version_request.APIVersionRequest()

        self.assertTrue(v2.matches(v1, v3))
        self.assertTrue(v2.matches(v1, v_null))
        self.assertTrue(v1.matches(v6, v2))
        self.assertTrue(v4.matches(v2, v7))
        self.assertTrue(v4.matches(v_null, v7))
        self.assertTrue(v4.matches(v_null, v8))
        self.assertFalse(v1.matches(v2, v3))
        self.assertFalse(v5.matches(v2, v4))
        self.assertFalse(v2.matches(v3, v1))

        self.assertRaises(ValueError, v_null.matches, v1, v3)

    def test_get_string(self):
        v1_string = "3.23"
        v1 = api_version_request.APIVersionRequest(v1_string)
        self.assertEqual(v1_string, v1.get_string())

        self.assertRaises(ValueError,
                          api_version_request.APIVersionRequest().get_string)
