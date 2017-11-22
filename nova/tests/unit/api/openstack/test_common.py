# Copyright 2010 OpenStack Foundation
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

"""
Test suites for 'common' code used throughout the OpenStack HTTP API.
"""

import mock
import six
from testtools import matchers
import webob
import webob.exc
import webob.multidict

from nova.api.openstack import common
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


class LimiterTest(test.NoDBTestCase):
    """Unit tests for the `nova.api.openstack.common.limited` method which
    takes in a list of items and, depending on the 'offset' and 'limit' GET
    params, returns a subset or complete set of the given items.
    """

    def setUp(self):
        """Run before each test."""
        super(LimiterTest, self).setUp()
        self.tiny = range(1)
        self.small = range(10)
        self.medium = range(1000)
        self.large = range(10000)

    def test_limiter_offset_zero(self):
        # Test offset key works with 0.
        req = webob.Request.blank('/?offset=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_offset_medium(self):
        # Test offset key works with a medium sized number.
        req = webob.Request.blank('/?offset=10')
        self.assertEqual(0, len(common.limited(self.tiny, req)))
        self.assertEqual(common.limited(self.small, req), self.small[10:])
        self.assertEqual(common.limited(self.medium, req), self.medium[10:])
        self.assertEqual(common.limited(self.large, req), self.large[10:1010])

    def test_limiter_offset_over_max(self):
        # Test offset key works with a number over 1000 (max_limit).
        req = webob.Request.blank('/?offset=1001')
        self.assertEqual(0, len(common.limited(self.tiny, req)))
        self.assertEqual(0, len(common.limited(self.small, req)))
        self.assertEqual(0, len(common.limited(self.medium, req)))
        self.assertEqual(
            common.limited(self.large, req), self.large[1001:2001])

    def test_limiter_offset_blank(self):
        # Test offset key works with a blank offset.
        req = webob.Request.blank('/?offset=')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_offset_bad(self):
        # Test offset key works with a BAD offset.
        req = webob.Request.blank(u'/?offset=\u0020aa')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_nothing(self):
        # Test request with no offset or limit.
        req = webob.Request.blank('/')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_zero(self):
        # Test limit of zero.
        req = webob.Request.blank('/?limit=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_medium(self):
        # Test limit of 10.
        req = webob.Request.blank('/?limit=10')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium[:10])
        self.assertEqual(common.limited(self.large, req), self.large[:10])

    def test_limiter_limit_over_max(self):
        # Test limit of 3000.
        req = webob.Request.blank('/?limit=3000')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_and_offset(self):
        # Test request with both limit and offset.
        items = range(2000)
        req = webob.Request.blank('/?offset=1&limit=3')
        self.assertEqual(common.limited(items, req), items[1:4])
        req = webob.Request.blank('/?offset=3&limit=0')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = webob.Request.blank('/?offset=3&limit=1500')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = webob.Request.blank('/?offset=3000&limit=10')
        self.assertEqual(0, len(common.limited(items, req)))

    def test_limiter_custom_max_limit(self):
        # Test a max_limit other than 1000.
        max_limit = 2000
        self.flags(max_limit=max_limit, group='api')
        items = range(max_limit)
        req = webob.Request.blank('/?offset=1&limit=3')
        self.assertEqual(
            common.limited(items, req), items[1:4])
        req = webob.Request.blank('/?offset=3&limit=0')
        self.assertEqual(
            common.limited(items, req), items[3:])
        req = webob.Request.blank('/?offset=3&limit=2500')
        self.assertEqual(
            common.limited(items, req), items[3:])
        req = webob.Request.blank('/?offset=3000&limit=10')
        self.assertEqual(0, len(common.limited(items, req)))

    def test_limiter_negative_limit(self):
        # Test a negative limit.
        req = webob.Request.blank('/?limit=-3000')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_negative_offset(self):
        # Test a negative offset.
        req = webob.Request.blank('/?offset=-30')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)


class SortParamUtilsTest(test.NoDBTestCase):

    def test_get_sort_params_defaults(self):
        '''Verifies the default sort key and direction.'''
        sort_keys, sort_dirs = common.get_sort_params({})
        self.assertEqual(['created_at'], sort_keys)
        self.assertEqual(['desc'], sort_dirs)

    def test_get_sort_params_override_defaults(self):
        '''Verifies that the defaults can be overridden.'''
        sort_keys, sort_dirs = common.get_sort_params({}, default_key='key1',
                                                      default_dir='dir1')
        self.assertEqual(['key1'], sort_keys)
        self.assertEqual(['dir1'], sort_dirs)

        sort_keys, sort_dirs = common.get_sort_params({}, default_key=None,
                                                      default_dir=None)
        self.assertEqual([], sort_keys)
        self.assertEqual([], sort_dirs)

    def test_get_sort_params_single_value(self):
        '''Verifies a single sort key and direction.'''
        params = webob.multidict.MultiDict()
        params.add('sort_key', 'key1')
        params.add('sort_dir', 'dir1')
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        self.assertEqual(['dir1'], sort_dirs)

    def test_get_sort_params_single_with_default(self):
        '''Verifies a single sort value with a default.'''
        params = webob.multidict.MultiDict()
        params.add('sort_key', 'key1')
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1'], sort_keys)
        # sort_key was supplied, sort_dir should be defaulted
        self.assertEqual(['desc'], sort_dirs)

        params = webob.multidict.MultiDict()
        params.add('sort_dir', 'dir1')
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['created_at'], sort_keys)
        # sort_dir was supplied, sort_key should be defaulted
        self.assertEqual(['dir1'], sort_dirs)

    def test_get_sort_params_multiple_values(self):
        '''Verifies multiple sort parameter values.'''
        params = webob.multidict.MultiDict()
        params.add('sort_key', 'key1')
        params.add('sort_key', 'key2')
        params.add('sort_key', 'key3')
        params.add('sort_dir', 'dir1')
        params.add('sort_dir', 'dir2')
        params.add('sort_dir', 'dir3')
        sort_keys, sort_dirs = common.get_sort_params(params)
        self.assertEqual(['key1', 'key2', 'key3'], sort_keys)
        self.assertEqual(['dir1', 'dir2', 'dir3'], sort_dirs)
        # Also ensure that the input parameters are not modified
        sort_key_vals = []
        sort_dir_vals = []
        while 'sort_key' in params:
            sort_key_vals.append(params.pop('sort_key'))
        while 'sort_dir' in params:
            sort_dir_vals.append(params.pop('sort_dir'))
        self.assertEqual(['key1', 'key2', 'key3'], sort_key_vals)
        self.assertEqual(['dir1', 'dir2', 'dir3'], sort_dir_vals)
        self.assertEqual(0, len(params))


class PaginationParamsTest(test.NoDBTestCase):
    """Unit tests for the `nova.api.openstack.common.get_pagination_params`
    method which takes in a request object and returns 'marker' and 'limit'
    GET params.
    """

    def test_no_params(self):
        # Test no params.
        req = webob.Request.blank('/')
        self.assertEqual(common.get_pagination_params(req), {})

    def test_valid_marker(self):
        # Test valid marker param.
        req = webob.Request.blank(
                '/?marker=263abb28-1de6-412f-b00b-f0ee0c4333c2')
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': '263abb28-1de6-412f-b00b-f0ee0c4333c2'})

    def test_valid_limit(self):
        # Test valid limit param.
        req = webob.Request.blank('/?limit=10')
        self.assertEqual(common.get_pagination_params(req), {'limit': 10})

    def test_invalid_limit(self):
        # Test invalid limit param.
        req = webob.Request.blank('/?limit=-2')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params, req)

    def test_valid_limit_and_marker(self):
        # Test valid limit and marker parameters.
        marker = '263abb28-1de6-412f-b00b-f0ee0c4333c2'
        req = webob.Request.blank('/?limit=20&marker=%s' % marker)
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': marker, 'limit': 20})

    def test_valid_page_size(self):
        # Test valid page_size param.
        req = webob.Request.blank('/?page_size=10')
        self.assertEqual(common.get_pagination_params(req),
                         {'page_size': 10})

    def test_invalid_page_size(self):
        # Test invalid page_size param.
        req = webob.Request.blank('/?page_size=-2')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params, req)

    def test_valid_limit_and_page_size(self):
        # Test valid limit and page_size parameters.
        req = webob.Request.blank('/?limit=20&page_size=5')
        self.assertEqual(common.get_pagination_params(req),
                         {'page_size': 5, 'limit': 20})


class MiscFunctionsTest(test.TestCase):

    def test_remove_trailing_version_from_href(self):
        fixture = 'http://www.testsite.com/v1.1'
        expected = 'http://www.testsite.com'
        actual = common.remove_trailing_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_trailing_version_from_href_2(self):
        fixture = 'http://www.testsite.com/compute/v1.1'
        expected = 'http://www.testsite.com/compute'
        actual = common.remove_trailing_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_trailing_version_from_href_3(self):
        fixture = 'http://www.testsite.com/v1.1/images/v10.5'
        expected = 'http://www.testsite.com/v1.1/images'
        actual = common.remove_trailing_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_trailing_version_from_href_bad_request(self):
        fixture = 'http://www.testsite.com/v1.1/images'
        self.assertRaises(ValueError,
                          common.remove_trailing_version_from_href,
                          fixture)

    def test_remove_trailing_version_from_href_bad_request_2(self):
        fixture = 'http://www.testsite.com/images/v'
        self.assertRaises(ValueError,
                          common.remove_trailing_version_from_href,
                          fixture)

    def test_remove_trailing_version_from_href_bad_request_3(self):
        fixture = 'http://www.testsite.com/v1.1images'
        self.assertRaises(ValueError,
                          common.remove_trailing_version_from_href,
                          fixture)

    def test_get_id_from_href_with_int_url(self):
        fixture = 'http://www.testsite.com/dir/45'
        actual = common.get_id_from_href(fixture)
        expected = '45'
        self.assertEqual(actual, expected)

    def test_get_id_from_href_with_int(self):
        fixture = '45'
        actual = common.get_id_from_href(fixture)
        expected = '45'
        self.assertEqual(actual, expected)

    def test_get_id_from_href_with_int_url_query(self):
        fixture = 'http://www.testsite.com/dir/45?asdf=jkl'
        actual = common.get_id_from_href(fixture)
        expected = '45'
        self.assertEqual(actual, expected)

    def test_get_id_from_href_with_uuid_url(self):
        fixture = 'http://www.testsite.com/dir/abc123'
        actual = common.get_id_from_href(fixture)
        expected = "abc123"
        self.assertEqual(actual, expected)

    def test_get_id_from_href_with_uuid_url_query(self):
        fixture = 'http://www.testsite.com/dir/abc123?asdf=jkl'
        actual = common.get_id_from_href(fixture)
        expected = "abc123"
        self.assertEqual(actual, expected)

    def test_get_id_from_href_with_uuid(self):
        fixture = 'abc123'
        actual = common.get_id_from_href(fixture)
        expected = 'abc123'
        self.assertEqual(actual, expected)

    def test_raise_http_conflict_for_instance_invalid_state(self):
        exc = exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method',
                instance_uuid='fake')
        try:
            common.raise_http_conflict_for_instance_invalid_state(exc,
                    'meow', 'fake_server_id')
        except webob.exc.HTTPConflict as e:
            self.assertEqual(six.text_type(e),
                "Cannot 'meow' instance fake_server_id while it is in "
                "fake_attr fake_state")
        else:
            self.fail("webob.exc.HTTPConflict was not raised")

    def test_status_from_state(self):
        for vm_state in (vm_states.ACTIVE, vm_states.STOPPED):
            for task_state in (task_states.RESIZE_PREP,
                               task_states.RESIZE_MIGRATING,
                               task_states.RESIZE_MIGRATED,
                               task_states.RESIZE_FINISH):
                actual = common.status_from_state(vm_state, task_state)
                expected = 'RESIZE'
                self.assertEqual(expected, actual)

    def test_status_rebuild_from_state(self):
        for vm_state in (vm_states.ACTIVE, vm_states.STOPPED,
                         vm_states.ERROR):
            for task_state in (task_states.REBUILDING,
                               task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                               task_states.REBUILD_SPAWNING):
                actual = common.status_from_state(vm_state, task_state)
                expected = 'REBUILD'
                self.assertEqual(expected, actual)

    def test_status_migrating_from_state(self):
        for vm_state in (vm_states.ACTIVE, vm_states.PAUSED):
            task_state = task_states.MIGRATING
            actual = common.status_from_state(vm_state, task_state)
            expected = 'MIGRATING'
            self.assertEqual(expected, actual)

    def test_task_and_vm_state_from_status(self):
        fixture1 = ['reboot']
        actual = common.task_and_vm_state_from_status(fixture1)
        expected = [vm_states.ACTIVE], [task_states.REBOOT_PENDING,
                                        task_states.REBOOT_STARTED,
                                        task_states.REBOOTING]
        self.assertEqual(expected, actual)

        fixture2 = ['resize']
        actual = common.task_and_vm_state_from_status(fixture2)
        expected = ([vm_states.ACTIVE, vm_states.STOPPED],
                    [task_states.RESIZE_FINISH,
                     task_states.RESIZE_MIGRATED,
                     task_states.RESIZE_MIGRATING,
                     task_states.RESIZE_PREP])
        self.assertEqual(expected, actual)

        fixture3 = ['resize', 'reboot']
        actual = common.task_and_vm_state_from_status(fixture3)
        expected = ([vm_states.ACTIVE, vm_states.STOPPED],
                    [task_states.REBOOT_PENDING,
                     task_states.REBOOT_STARTED,
                     task_states.REBOOTING,
                     task_states.RESIZE_FINISH,
                     task_states.RESIZE_MIGRATED,
                     task_states.RESIZE_MIGRATING,
                     task_states.RESIZE_PREP])
        self.assertEqual(expected, actual)

    def test_is_all_tenants_true(self):
        for value in ('', '1', 'true', 'True'):
            search_opts = {'all_tenants': value}
            self.assertTrue(common.is_all_tenants(search_opts))
            self.assertIn('all_tenants', search_opts)

    def test_is_all_tenants_false(self):
        for value in ('0', 'false', 'False'):
            search_opts = {'all_tenants': value}
            self.assertFalse(common.is_all_tenants(search_opts))
            self.assertIn('all_tenants', search_opts)

    def test_is_all_tenants_missing(self):
        self.assertFalse(common.is_all_tenants({}))

    def test_is_all_tenants_invalid(self):
        search_opts = {'all_tenants': 'wonk'}
        self.assertRaises(exception.InvalidInput, common.is_all_tenants,
                          search_opts)


class TestCollectionLinks(test.NoDBTestCase):
    """Tests the _get_collection_links method."""

    @mock.patch('nova.api.openstack.common.ViewBuilder._get_next_link')
    def test_items_less_than_limit(self, href_link_mock):
        items = [
            {"uuid": "123"}
        ]
        req = mock.MagicMock()
        params = mock.PropertyMock(return_value=dict(limit=10))
        type(req).params = params

        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, items, "ignored", "uuid")

        self.assertFalse(href_link_mock.called)
        self.assertThat(results, matchers.HasLength(0))

    @mock.patch('nova.api.openstack.common.ViewBuilder._get_next_link')
    def test_items_equals_given_limit(self, href_link_mock):
        items = [
            {"uuid": "123"}
        ]
        req = mock.MagicMock()
        params = mock.PropertyMock(return_value=dict(limit=1))
        type(req).params = params

        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, items,
                                                mock.sentinel.coll_key,
                                                "uuid")

        href_link_mock.assert_called_once_with(req, "123",
                                               mock.sentinel.coll_key)
        self.assertThat(results, matchers.HasLength(1))

    @mock.patch('nova.api.openstack.common.ViewBuilder._get_next_link')
    def test_items_equals_default_limit(self, href_link_mock):
        items = [
            {"uuid": "123"}
        ]
        req = mock.MagicMock()
        params = mock.PropertyMock(return_value=dict())
        type(req).params = params
        self.flags(max_limit=1, group='api')

        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, items,
                                                mock.sentinel.coll_key,
                                                "uuid")

        href_link_mock.assert_called_once_with(req, "123",
                                               mock.sentinel.coll_key)
        self.assertThat(results, matchers.HasLength(1))

    @mock.patch('nova.api.openstack.common.ViewBuilder._get_next_link')
    def test_items_equals_default_limit_with_given(self, href_link_mock):
        items = [
            {"uuid": "123"}
        ]
        req = mock.MagicMock()
        # Given limit is greater than default max, only return default max
        params = mock.PropertyMock(return_value=dict(limit=2))
        type(req).params = params
        self.flags(max_limit=1, group='api')

        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, items,
                                                mock.sentinel.coll_key,
                                                "uuid")

        href_link_mock.assert_called_once_with(req, "123",
                                               mock.sentinel.coll_key)
        self.assertThat(results, matchers.HasLength(1))


class LinkPrefixTest(test.NoDBTestCase):

    def test_update_link_prefix(self):
        vb = common.ViewBuilder()
        result = vb._update_link_prefix("http://192.168.0.243:24/",
                                        "http://127.0.0.1/compute")
        self.assertEqual("http://127.0.0.1/compute", result)

        result = vb._update_link_prefix("http://foo.x.com/v1",
                                        "http://new.prefix.com")
        self.assertEqual("http://new.prefix.com/v1", result)

        result = vb._update_link_prefix(
                "http://foo.x.com/v1",
                "http://new.prefix.com:20455/new_extra_prefix")
        self.assertEqual("http://new.prefix.com:20455/new_extra_prefix/v1",
                         result)


class UrlJoinTest(test.NoDBTestCase):
    def test_url_join(self):
        pieces = ["one", "two", "three"]
        joined = common.url_join(*pieces)
        self.assertEqual("one/two/three", joined)

    def test_url_join_extra_slashes(self):
        pieces = ["one/", "/two//", "/three/"]
        joined = common.url_join(*pieces)
        self.assertEqual("one/two/three", joined)

    def test_url_join_trailing_slash(self):
        pieces = ["one", "two", "three", ""]
        joined = common.url_join(*pieces)
        self.assertEqual("one/two/three/", joined)

    def test_url_join_empty_list(self):
        pieces = []
        joined = common.url_join(*pieces)
        self.assertEqual("", joined)

    def test_url_join_single_empty_string(self):
        pieces = [""]
        joined = common.url_join(*pieces)
        self.assertEqual("", joined)

    def test_url_join_single_slash(self):
        pieces = ["/"]
        joined = common.url_join(*pieces)
        self.assertEqual("", joined)


class ViewBuilderLinkTest(test.NoDBTestCase):
    project_id = "fake"
    api_version = "2.1"

    def setUp(self):
        super(ViewBuilderLinkTest, self).setUp()
        self.request = self.req("/%s" % self.project_id)
        self.vb = common.ViewBuilder()

    def req(self, url, use_admin_context=False):
        return fakes.HTTPRequest.blank(url,
                use_admin_context=use_admin_context, version=self.api_version)

    def test_get_project_id(self):
        proj_id = self.vb._get_project_id(self.request)
        self.assertEqual(self.project_id, proj_id)

    def test_get_project_id_with_none_project_id(self):
        self.request.environ["nova.context"].project_id = None
        proj_id = self.vb._get_project_id(self.request)
        self.assertEqual('', proj_id)

    def test_get_next_link(self):
        identifier = "identifier"
        collection = "collection"
        next_link = self.vb._get_next_link(self.request, identifier,
                                           collection)
        expected = "/".join((self.request.url,
                             "%s?marker=%s" % (collection, identifier)))
        self.assertEqual(expected, next_link)

    def test_get_href_link(self):
        identifier = "identifier"
        collection = "collection"
        href_link = self.vb._get_href_link(self.request, identifier,
                                           collection)
        expected = "/".join((self.request.url, collection, identifier))
        self.assertEqual(expected, href_link)

    def test_get_bookmark_link(self):
        identifier = "identifier"
        collection = "collection"
        bookmark_link = self.vb._get_bookmark_link(self.request, identifier,
                                                   collection)
        bmk_url = common.remove_trailing_version_from_href(
                self.request.application_url)
        expected = "/".join((bmk_url, self.project_id, collection, identifier))
        self.assertEqual(expected, bookmark_link)
