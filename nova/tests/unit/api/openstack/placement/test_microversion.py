# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tests for placement microversion handling."""

import collections
import operator
import webob

import mock

# import the handlers to load up handler decorators
import nova.api.openstack.placement.handler  # noqa
from nova.api.openstack.placement import microversion
from nova import test


def handler():
    return True


class TestMicroversionFindMethod(test.NoDBTestCase):
    def test_method_405(self):
        self.assertRaises(webob.exc.HTTPMethodNotAllowed,
                          microversion._find_method, handler, '1.1', 405)

    def test_method_404(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          microversion._find_method, handler, '1.1', 404)


class TestMicroversionDecoration(test.NoDBTestCase):

    @mock.patch('nova.api.openstack.placement.microversion.VERSIONED_METHODS',
                new=collections.defaultdict(list))
    def test_methods_structure(self):
        """Test that VERSIONED_METHODS gets data as expected."""
        self.assertEqual(0, len(microversion.VERSIONED_METHODS))
        fully_qualified_method = microversion._fully_qualified_name(
            handler)
        microversion.version_handler('1.1', '1.10')(handler)
        microversion.version_handler('2.0')(handler)

        methods_data = microversion.VERSIONED_METHODS[fully_qualified_method]

        stored_method_data = methods_data[-1]
        self.assertEqual(2, len(methods_data))
        self.assertEqual(microversion.Version(1, 1), stored_method_data[0])
        self.assertEqual(microversion.Version(1, 10), stored_method_data[1])
        self.assertEqual(handler, stored_method_data[2])
        self.assertEqual(microversion.Version(2, 0), methods_data[0][0])

    def test_version_handler_float_exception(self):
        self.assertRaises(AttributeError,
                          microversion.version_handler(1.1),
                          handler)

    def test_version_handler_nan_exception(self):
        self.assertRaises(TypeError,
                          microversion.version_handler('cow'),
                          handler)

    def test_version_handler_tuple_exception(self):
        self.assertRaises(AttributeError,
                          microversion.version_handler((1, 1)),
                          handler)


class TestMicroversionIntersection(test.NoDBTestCase):
    """Test that there are no overlaps in the versioned handlers."""

    # If you add versioned handlers you need to update this value to
    # reflect the change. The value is the total number of methods
    # with different names, not the total number overall. That is,
    # if you add two different versions of method 'foobar' the
    # number only goes up by one if no other version foobar yet
    # exists. This operates as a simple sanity check.
    TOTAL_VERSIONED_METHODS = 19

    def test_methods_versioned(self):
        methods_data = microversion.VERSIONED_METHODS
        self.assertEqual(self.TOTAL_VERSIONED_METHODS, len(methods_data))

    @staticmethod
    def _check_intersection(method_info):
        # See check_for_versions_intersection in
        # nova.api.openstack.wsgi.
        pairs = []
        counter = 0
        for min_ver, max_ver, func in method_info:
            pairs.append((min_ver, 1, func))
            pairs.append((max_ver, -1, func))

        pairs.sort(key=operator.itemgetter(0))

        for p in pairs:
            counter += p[1]
            if counter > 1:
                return True
        return False

    @mock.patch('nova.api.openstack.placement.microversion.VERSIONED_METHODS',
                new=collections.defaultdict(list))
    def test_faked_intersection(self):
        microversion.version_handler('1.0', '1.9')(handler)
        microversion.version_handler('1.8', '2.0')(handler)

        for method_info in microversion.VERSIONED_METHODS.values():
            self.assertTrue(self._check_intersection(method_info))

    @mock.patch('nova.api.openstack.placement.microversion.VERSIONED_METHODS',
                new=collections.defaultdict(list))
    def test_faked_non_intersection(self):
        microversion.version_handler('1.0', '1.8')(handler)
        microversion.version_handler('1.9', '2.0')(handler)

        for method_info in microversion.VERSIONED_METHODS.values():
            self.assertFalse(self._check_intersection(method_info))

    def test_check_real_for_intersection(self):
        """Check the real handlers to make sure there is no intersctions."""
        for method_name, method_info in microversion.VERSIONED_METHODS.items():
            self.assertFalse(
                self._check_intersection(method_info),
                'method %s has intersecting versioned handlers' % method_name)


class MicroversionSequentialTest(test.NoDBTestCase):

    def test_microversion_sequential(self):
        for method_name, method_list in microversion.VERSIONED_METHODS.items():
            previous_min_version = method_list[0][0]
            for method in method_list[1:]:
                previous_min_version = microversion.parse_version_string(
                    '%s.%s' % (previous_min_version.major,
                               previous_min_version.minor - 1))
                self.assertEqual(previous_min_version, method[1],
                    "The microversions aren't sequential in the mehtod %s" %
                    method_name)
                previous_min_version = method[0]
