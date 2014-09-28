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

from lxml import etree
import mock
from testtools import matchers
import webob
import webob.exc
import xml.dom.minidom as minidom

from nova.api.openstack import common
from nova.api.openstack import xmlutil
from nova.compute import task_states
from nova.compute import vm_states
from nova import exception
from nova import test
from nova.tests import utils


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


class LimiterTest(test.TestCase):
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
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), self.small[10:])
        self.assertEqual(common.limited(self.medium, req), self.medium[10:])
        self.assertEqual(common.limited(self.large, req), self.large[10:1010])

    def test_limiter_offset_over_max(self):
        # Test offset key works with a number over 1000 (max_limit).
        req = webob.Request.blank('/?offset=1001')
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), [])
        self.assertEqual(common.limited(self.medium, req), [])
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
        self.assertEqual(common.limited(items, req), [])

    def test_limiter_custom_max_limit(self):
        # Test a max_limit other than 1000.
        items = range(2000)
        req = webob.Request.blank('/?offset=1&limit=3')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[1:4])
        req = webob.Request.blank('/?offset=3&limit=0')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = webob.Request.blank('/?offset=3&limit=2500')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = webob.Request.blank('/?offset=3000&limit=10')
        self.assertEqual(common.limited(items, req, max_limit=2000), [])

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


class PaginationParamsTest(test.TestCase):
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

    def test_remove_major_version_from_href(self):
        fixture = 'http://www.testsite.com/v1/images'
        expected = 'http://www.testsite.com/images'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href(self):
        fixture = 'http://www.testsite.com/v1.1/images'
        expected = 'http://www.testsite.com/images'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_2(self):
        fixture = 'http://www.testsite.com/v1.1/'
        expected = 'http://www.testsite.com/'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_3(self):
        fixture = 'http://www.testsite.com/v10.10'
        expected = 'http://www.testsite.com'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_4(self):
        fixture = 'http://www.testsite.com/v1.1/images/v10.5'
        expected = 'http://www.testsite.com/images/v10.5'
        actual = common.remove_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_remove_version_from_href_bad_request(self):
        fixture = 'http://www.testsite.com/1.1/images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)

    def test_remove_version_from_href_bad_request_2(self):
        fixture = 'http://www.testsite.com/v/images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
                          fixture)

    def test_remove_version_from_href_bad_request_3(self):
        fixture = 'http://www.testsite.com/v1.1images'
        self.assertRaises(ValueError,
                          common.remove_version_from_href,
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
                    'meow')
        except webob.exc.HTTPConflict as e:
            self.assertEqual(unicode(e),
                "Cannot 'meow' while instance is in fake_attr fake_state")
        else:
            self.fail("webob.exc.HTTPConflict was not raised")

    def test_check_img_metadata_properties_quota_valid_metadata(self):
        ctxt = utils.get_test_admin_context()
        metadata1 = {"key": "value"}
        actual = common.check_img_metadata_properties_quota(ctxt, metadata1)
        self.assertIsNone(actual)

        metadata2 = {"key": "v" * 260}
        actual = common.check_img_metadata_properties_quota(ctxt, metadata2)
        self.assertIsNone(actual)

        metadata3 = {"key": ""}
        actual = common.check_img_metadata_properties_quota(ctxt, metadata3)
        self.assertIsNone(actual)

    def test_check_img_metadata_properties_quota_inv_metadata(self):
        ctxt = utils.get_test_admin_context()
        metadata1 = {"a" * 260: "value"}
        self.assertRaises(webob.exc.HTTPBadRequest,
                common.check_img_metadata_properties_quota, ctxt, metadata1)

        metadata2 = {"": "value"}
        self.assertRaises(webob.exc.HTTPBadRequest,
                common.check_img_metadata_properties_quota, ctxt, metadata2)

        metadata3 = "invalid metadata"
        self.assertRaises(webob.exc.HTTPBadRequest,
                common.check_img_metadata_properties_quota, ctxt, metadata3)

        metadata4 = None
        self.assertIsNone(common.check_img_metadata_properties_quota(ctxt,
                                                        metadata4))
        metadata5 = {}
        self.assertIsNone(common.check_img_metadata_properties_quota(ctxt,
                                                        metadata5))

    def test_status_from_state(self):
        for vm_state in (vm_states.ACTIVE, vm_states.STOPPED):
            for task_state in (task_states.RESIZE_PREP,
                               task_states.RESIZE_MIGRATING,
                               task_states.RESIZE_MIGRATED,
                               task_states.RESIZE_FINISH):
                actual = common.status_from_state(vm_state, task_state)
                expected = 'RESIZE'
                self.assertEqual(expected, actual)

    def test_task_and_vm_state_from_status(self):
        fixture1 = 'reboot'
        actual = common.task_and_vm_state_from_status(fixture1)
        expected = [vm_states.ACTIVE], [task_states.REBOOT_PENDING,
                                        task_states.REBOOT_STARTED,
                                        task_states.REBOOTING]
        self.assertEqual(expected, actual)

        fixture2 = 'resize'
        actual = common.task_and_vm_state_from_status(fixture2)
        expected = ([vm_states.ACTIVE, vm_states.STOPPED],
                    [task_states.RESIZE_FINISH,
                     task_states.RESIZE_MIGRATED,
                     task_states.RESIZE_MIGRATING,
                     task_states.RESIZE_PREP])
        self.assertEqual(expected, actual)


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

        href_link_mock.assert_not_called()
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
        self.flags(osapi_max_limit=1)

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
        # Given limit is greater then default max, only return default max
        params = mock.PropertyMock(return_value=dict(limit=2))
        type(req).params = params
        self.flags(osapi_max_limit=1)

        builder = common.ViewBuilder()
        results = builder._get_collection_links(req, items,
                                                mock.sentinel.coll_key,
                                                "uuid")

        href_link_mock.assert_called_once_with(req, "123",
                                               mock.sentinel.coll_key)
        self.assertThat(results, matchers.HasLength(1))


class MetadataXMLDeserializationTest(test.TestCase):

    deserializer = common.MetadataXMLDeserializer()

    def test_create(self):
        request_body = """
        <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
            <meta key='123'>asdf</meta>
            <meta key='567'>jkl;</meta>
        </metadata>"""
        output = self.deserializer.deserialize(request_body, 'create')
        expected = {"body": {"metadata": {"123": "asdf", "567": "jkl;"}}}
        self.assertEqual(output, expected)

    def test_create_empty(self):
        request_body = """
        <metadata xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        output = self.deserializer.deserialize(request_body, 'create')
        expected = {"body": {"metadata": {}}}
        self.assertEqual(output, expected)

    def test_update_all(self):
        request_body = """
        <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
            <meta key='123'>asdf</meta>
            <meta key='567'>jkl;</meta>
        </metadata>"""
        output = self.deserializer.deserialize(request_body, 'update_all')
        expected = {"body": {"metadata": {"123": "asdf", "567": "jkl;"}}}
        self.assertEqual(output, expected)

    def test_update(self):
        request_body = """
        <meta xmlns="http://docs.openstack.org/compute/api/v1.1"
              key='123'>asdf</meta>"""
        output = self.deserializer.deserialize(request_body, 'update')
        expected = {"body": {"meta": {"123": "asdf"}}}
        self.assertEqual(output, expected)


class MetadataXMLSerializationTest(test.TestCase):

    def test_xml_declaration(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                'one': 'two',
                'three': 'four',
            },
        }

        output = serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_index(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                'one': 'two',
                'three': 'four',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'metadata')
        metadata_dict = fixture['metadata']
        metadata_elems = root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = metadata_dict.items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

    def test_index_null(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                None: None,
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'metadata')
        metadata_dict = fixture['metadata']
        metadata_elems = root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = metadata_dict.items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

    def test_index_unicode(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                u'three': u'Jos\xe9',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'metadata')
        metadata_dict = fixture['metadata']
        metadata_elems = root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 1)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = metadata_dict.items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(metadata_elem.text.strip(), meta_value)

    def test_show(self):
        serializer = common.MetaItemTemplate()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        meta_dict = fixture['meta']
        (meta_key, meta_value) = meta_dict.items()[0]
        self.assertEqual(str(root.get('key')), str(meta_key))
        self.assertEqual(root.text.strip(), meta_value)

    def test_update_all(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                'key6': 'value6',
                'key4': 'value4',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'metadata')
        metadata_dict = fixture['metadata']
        metadata_elems = root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 2)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = metadata_dict.items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))

    def test_update_item(self):
        serializer = common.MetaItemTemplate()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        meta_dict = fixture['meta']
        (meta_key, meta_value) = meta_dict.items()[0]
        self.assertEqual(str(root.get('key')), str(meta_key))
        self.assertEqual(root.text.strip(), meta_value)

    def test_create(self):
        serializer = common.MetadataTemplate()
        fixture = {
            'metadata': {
                'key9': 'value9',
                'key2': 'value2',
                'key1': 'value1',
            },
        }
        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'metadata')
        metadata_dict = fixture['metadata']
        metadata_elems = root.findall('{0}meta'.format(NS))
        self.assertEqual(len(metadata_elems), 3)
        for i, metadata_elem in enumerate(metadata_elems):
            (meta_key, meta_value) = metadata_dict.items()[i]
            self.assertEqual(str(metadata_elem.get('key')), str(meta_key))
            self.assertEqual(str(metadata_elem.text).strip(), str(meta_value))
        actual = minidom.parseString(output.replace("  ", ""))

        expected = minidom.parseString("""
            <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
                <meta key="key2">value2</meta>
                <meta key="key9">value9</meta>
                <meta key="key1">value1</meta>
            </metadata>
        """.replace("  ", "").replace("\n", ""))

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_metadata_deserializer(self):
        """Should throw a 400 error on corrupt xml."""
        deserializer = common.MetadataXMLDeserializer()
        self.assertRaises(
                exception.MalformedRequestBody,
                deserializer.deserialize,
                utils.killer_xml_body())
