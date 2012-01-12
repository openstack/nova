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

"""
Test suites for 'common' code used throughout the OpenStack HTTP API.
"""

from lxml import etree
import webob.exc
# FIXME(comstud): Don't import classes (HACKING)
from webob import Request
import xml.dom.minidom as minidom

from nova import exception
from nova import test
from nova.api.openstack import common
from nova.api.openstack import xmlutil


NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


class LimiterTest(test.TestCase):
    """
    Unit tests for the `nova.api.openstack.common.limited` method which takes
    in a list of items and, depending on the 'offset' and 'limit' GET params,
    returns a subset or complete set of the given items.
    """

    def setUp(self):
        """ Run before each test. """
        super(LimiterTest, self).setUp()
        self.tiny = range(1)
        self.small = range(10)
        self.medium = range(1000)
        self.large = range(10000)

    def test_limiter_offset_zero(self):
        """ Test offset key works with 0. """
        req = Request.blank('/?offset=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_offset_medium(self):
        """ Test offset key works with a medium sized number. """
        req = Request.blank('/?offset=10')
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), self.small[10:])
        self.assertEqual(common.limited(self.medium, req), self.medium[10:])
        self.assertEqual(common.limited(self.large, req), self.large[10:1010])

    def test_limiter_offset_over_max(self):
        """ Test offset key works with a number over 1000 (max_limit). """
        req = Request.blank('/?offset=1001')
        self.assertEqual(common.limited(self.tiny, req), [])
        self.assertEqual(common.limited(self.small, req), [])
        self.assertEqual(common.limited(self.medium, req), [])
        self.assertEqual(
            common.limited(self.large, req), self.large[1001:2001])

    def test_limiter_offset_blank(self):
        """ Test offset key works with a blank offset. """
        req = Request.blank('/?offset=')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_offset_bad(self):
        """ Test offset key works with a BAD offset. """
        req = Request.blank(u'/?offset=\u0020aa')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_nothing(self):
        """ Test request with no offset or limit """
        req = Request.blank('/')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_zero(self):
        """ Test limit of zero. """
        req = Request.blank('/?limit=0')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_medium(self):
        """ Test limit of 10. """
        req = Request.blank('/?limit=10')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium[:10])
        self.assertEqual(common.limited(self.large, req), self.large[:10])

    def test_limiter_limit_over_max(self):
        """ Test limit of 3000. """
        req = Request.blank('/?limit=3000')
        self.assertEqual(common.limited(self.tiny, req), self.tiny)
        self.assertEqual(common.limited(self.small, req), self.small)
        self.assertEqual(common.limited(self.medium, req), self.medium)
        self.assertEqual(common.limited(self.large, req), self.large[:1000])

    def test_limiter_limit_and_offset(self):
        """ Test request with both limit and offset. """
        items = range(2000)
        req = Request.blank('/?offset=1&limit=3')
        self.assertEqual(common.limited(items, req), items[1:4])
        req = Request.blank('/?offset=3&limit=0')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = Request.blank('/?offset=3&limit=1500')
        self.assertEqual(common.limited(items, req), items[3:1003])
        req = Request.blank('/?offset=3000&limit=10')
        self.assertEqual(common.limited(items, req), [])

    def test_limiter_custom_max_limit(self):
        """ Test a max_limit other than 1000. """
        items = range(2000)
        req = Request.blank('/?offset=1&limit=3')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[1:4])
        req = Request.blank('/?offset=3&limit=0')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = Request.blank('/?offset=3&limit=2500')
        self.assertEqual(
            common.limited(items, req, max_limit=2000), items[3:])
        req = Request.blank('/?offset=3000&limit=10')
        self.assertEqual(common.limited(items, req, max_limit=2000), [])

    def test_limiter_negative_limit(self):
        """ Test a negative limit. """
        req = Request.blank('/?limit=-3000')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)

    def test_limiter_negative_offset(self):
        """ Test a negative offset. """
        req = Request.blank('/?offset=-30')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.limited, self.tiny, req)


class PaginationParamsTest(test.TestCase):
    """
    Unit tests for the `nova.api.openstack.common.get_pagination_params`
    method which takes in a request object and returns 'marker' and 'limit'
    GET params.
    """

    def test_no_params(self):
        """ Test no params. """
        req = Request.blank('/')
        self.assertEqual(common.get_pagination_params(req), {})

    def test_valid_marker(self):
        """ Test valid marker param. """
        req = Request.blank('/?marker=263abb28-1de6-412f-b00b-f0ee0c4333c2')
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': '263abb28-1de6-412f-b00b-f0ee0c4333c2'})

    def test_valid_limit(self):
        """ Test valid limit param. """
        req = Request.blank('/?limit=10')
        self.assertEqual(common.get_pagination_params(req), {'limit': 10})

    def test_invalid_limit(self):
        """ Test invalid limit param. """
        req = Request.blank('/?limit=-2')
        self.assertRaises(
            webob.exc.HTTPBadRequest, common.get_pagination_params, req)

    def test_valid_limit_and_marker(self):
        """ Test valid limit and marker parameters. """
        marker = '263abb28-1de6-412f-b00b-f0ee0c4333c2'
        req = Request.blank('/?limit=20&marker=%s' % marker)
        self.assertEqual(common.get_pagination_params(req),
                         {'marker': marker, 'limit': 20})


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

    def test_get_version_from_href(self):
        fixture = 'http://www.testsite.com/v1.1/images'
        expected = '1.1'
        actual = common.get_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_get_version_from_href_2(self):
        fixture = 'http://www.testsite.com/v1.1'
        expected = '1.1'
        actual = common.get_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_get_version_from_href_default(self):
        fixture = 'http://www.testsite.com/images'
        expected = '2'
        actual = common.get_version_from_href(fixture)
        self.assertEqual(actual, expected)

    def test_raise_http_conflict_for_instance_invalid_state(self):
        # Correct args
        exc = exception.InstanceInvalidState(attr='fake_attr',
                state='fake_state', method='fake_method')
        try:
            common.raise_http_conflict_for_instance_invalid_state(exc,
                    'meow')
        except Exception, e:
            self.assertTrue(isinstance(e, webob.exc.HTTPConflict))
            msg = str(e)
            self.assertEqual(msg,
                "Cannot 'meow' while instance is in fake_attr fake_state")
        else:
            self.fail("webob.exc.HTTPConflict was not raised")

        # Incorrect args
        exc = exception.InstanceInvalidState()
        try:
            common.raise_http_conflict_for_instance_invalid_state(exc,
                    'meow')
        except Exception, e:
            self.assertTrue(isinstance(e, webob.exc.HTTPConflict))
            msg = str(e)
            self.assertEqual(msg,
                "Instance is in an invalid state for 'meow'")
        else:
            self.fail("webob.exc.HTTPConflict was not raised")


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
        self.assertEquals(output, expected)

    def test_create_empty(self):
        request_body = """
        <metadata xmlns="http://docs.openstack.org/compute/api/v1.1"/>"""
        output = self.deserializer.deserialize(request_body, 'create')
        expected = {"body": {"metadata": {}}}
        self.assertEquals(output, expected)

    def test_update_all(self):
        request_body = """
        <metadata xmlns="http://docs.openstack.org/compute/api/v1.1">
            <meta key='123'>asdf</meta>
            <meta key='567'>jkl;</meta>
        </metadata>"""
        output = self.deserializer.deserialize(request_body, 'update_all')
        expected = {"body": {"metadata": {"123": "asdf", "567": "jkl;"}}}
        self.assertEquals(output, expected)

    def test_update(self):
        request_body = """
        <meta xmlns="http://docs.openstack.org/compute/api/v1.1"
              key='123'>asdf</meta>"""
        output = self.deserializer.deserialize(request_body, 'update')
        expected = {"body": {"meta": {"123": "asdf"}}}
        self.assertEquals(output, expected)


class MetadataXMLSerializationTest(test.TestCase):

    def test_xml_declaration(self):
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                'one': 'two',
                'three': 'four',
            },
        }

        output = serializer.serialize(fixture, 'index')
        print output
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_index(self):
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                'one': 'two',
                'three': 'four',
            },
        }
        output = serializer.serialize(fixture, 'index')
        print output
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
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                None: None,
            },
        }
        output = serializer.serialize(fixture, 'index')
        print output
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
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                u'three': u'Jos\xe9',
            },
        }
        output = serializer.serialize(fixture, 'index')
        print output
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
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.serialize(fixture, 'show')
        print output
        root = etree.XML(output)
        meta_dict = fixture['meta']
        (meta_key, meta_value) = meta_dict.items()[0]
        self.assertEqual(str(root.get('key')), str(meta_key))
        self.assertEqual(root.text.strip(), meta_value)

    def test_update_all(self):
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                'key6': 'value6',
                'key4': 'value4',
            },
        }
        output = serializer.serialize(fixture, 'update_all')
        print output
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
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'meta': {
                'one': 'two',
            },
        }
        output = serializer.serialize(fixture, 'update')
        print output
        root = etree.XML(output)
        meta_dict = fixture['meta']
        (meta_key, meta_value) = meta_dict.items()[0]
        self.assertEqual(str(root.get('key')), str(meta_key))
        self.assertEqual(root.text.strip(), meta_value)

    def test_create(self):
        serializer = common.MetadataXMLSerializer()
        fixture = {
            'metadata': {
                'key9': 'value9',
                'key2': 'value2',
                'key1': 'value1',
            },
        }
        output = serializer.serialize(fixture, 'create')
        print output
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

    def test_delete(self):
        serializer = common.MetadataXMLSerializer()
        output = serializer.serialize(None, 'delete')
        self.assertEqual(output, '')
