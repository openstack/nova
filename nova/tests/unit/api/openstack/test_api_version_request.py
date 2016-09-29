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
from nova.tests.unit.api.openstack import fakes


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
        vers1 = api_version_request.APIVersionRequest("2.0")
        vers2 = api_version_request.APIVersionRequest("2.5")
        vers3 = api_version_request.APIVersionRequest("5.23")
        vers4 = api_version_request.APIVersionRequest("2.0")
        v_null = api_version_request.APIVersionRequest()

        self.assertLess(v_null, vers2)
        self.assertLess(vers1, vers2)
        self.assertLessEqual(vers1, vers2)
        self.assertLessEqual(vers1, vers4)
        self.assertGreater(vers2, v_null)
        self.assertGreater(vers3, vers2)
        self.assertGreaterEqual(vers1, vers4)
        self.assertGreaterEqual(vers3, vers2)
        self.assertNotEqual(vers1, vers2)
        self.assertEqual(vers1, vers4)
        self.assertNotEqual(vers1, v_null)
        self.assertEqual(v_null, v_null)
        self.assertRaises(TypeError, vers1.__lt__, "2.1")

    def test_version_matches(self):
        vers1 = api_version_request.APIVersionRequest("2.0")
        vers2 = api_version_request.APIVersionRequest("2.5")
        vers3 = api_version_request.APIVersionRequest("2.45")
        vers4 = api_version_request.APIVersionRequest("3.3")
        vers5 = api_version_request.APIVersionRequest("3.23")
        vers6 = api_version_request.APIVersionRequest("2.0")
        vers7 = api_version_request.APIVersionRequest("3.3")
        vers8 = api_version_request.APIVersionRequest("4.0")
        v_null = api_version_request.APIVersionRequest()

        self.assertTrue(vers2.matches(vers1, vers3))
        self.assertTrue(vers2.matches(vers1, v_null))
        self.assertTrue(vers1.matches(vers6, vers2))
        self.assertTrue(vers4.matches(vers2, vers7))
        self.assertTrue(vers4.matches(v_null, vers7))
        self.assertTrue(vers4.matches(v_null, vers8))
        self.assertFalse(vers1.matches(vers2, vers3))
        self.assertFalse(vers5.matches(vers2, vers4))
        self.assertFalse(vers2.matches(vers3, vers1))

        self.assertRaises(ValueError, v_null.matches, vers1, vers3)

    def test_get_string(self):
        vers1_string = "3.23"
        vers1 = api_version_request.APIVersionRequest(vers1_string)
        self.assertEqual(vers1_string, vers1.get_string())

        self.assertRaises(ValueError,
                          api_version_request.APIVersionRequest().get_string)

    def test_is_supported_min_version(self):
        req = fakes.HTTPRequest.blank('/fake', version='2.5')

        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.4'))
        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.5'))
        self.assertFalse(api_version_request.is_supported(
            req, min_version='2.6'))

    def test_is_supported_max_version(self):
        req = fakes.HTTPRequest.blank('/fake', version='2.5')

        self.assertFalse(api_version_request.is_supported(
            req, max_version='2.4'))
        self.assertTrue(api_version_request.is_supported(
            req, max_version='2.5'))
        self.assertTrue(api_version_request.is_supported(
            req, max_version='2.6'))

    def test_is_supported_min_and_max_version(self):
        req = fakes.HTTPRequest.blank('/fake', version='2.5')

        self.assertFalse(api_version_request.is_supported(
            req, min_version='2.3', max_version='2.4'))
        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.3', max_version='2.5'))
        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.3', max_version='2.7'))
        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.5', max_version='2.7'))
        self.assertFalse(api_version_request.is_supported(
            req, min_version='2.6', max_version='2.7'))
        self.assertTrue(api_version_request.is_supported(
            req, min_version='2.5', max_version='2.5'))
        self.assertFalse(api_version_request.is_supported(
            req, min_version='2.10', max_version='2.1'))
