#    Copyright 2011 Justin Santa Barbara
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

import datetime
import hashlib
import os
import os.path
import tempfile

import eventlet
import fixtures
from keystoneauth1 import adapter as ks_adapter
from keystoneauth1 import exceptions as ks_exc
from keystoneauth1.identity import base as ks_identity
from keystoneauth1 import session as ks_session
import mock
import netaddr
from openstack import exceptions as sdk_exc
from oslo_config import cfg
from oslo_context import context as common_context
from oslo_context import fixture as context_fixture
from oslo_utils import encodeutils
from oslo_utils import fixture as utils_fixture
from oslo_utils import units
import six

from nova import context
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit.objects import test_objects
from nova.tests.unit import utils as test_utils
from nova import utils

CONF = cfg.CONF


class GenericUtilsTestCase(test.NoDBTestCase):
    def test_parse_server_string(self):
        result = utils.parse_server_string('::1')
        self.assertEqual(('::1', ''), result)
        result = utils.parse_server_string('[::1]:8773')
        self.assertEqual(('::1', '8773'), result)
        result = utils.parse_server_string('2001:db8::192.168.1.1')
        self.assertEqual(('2001:db8::192.168.1.1', ''), result)
        result = utils.parse_server_string('[2001:db8::192.168.1.1]:8773')
        self.assertEqual(('2001:db8::192.168.1.1', '8773'), result)
        result = utils.parse_server_string('192.168.1.1')
        self.assertEqual(('192.168.1.1', ''), result)
        result = utils.parse_server_string('192.168.1.2:8773')
        self.assertEqual(('192.168.1.2', '8773'), result)
        result = utils.parse_server_string('192.168.1.3')
        self.assertEqual(('192.168.1.3', ''), result)
        result = utils.parse_server_string('www.example.com:8443')
        self.assertEqual(('www.example.com', '8443'), result)
        result = utils.parse_server_string('www.example.com')
        self.assertEqual(('www.example.com', ''), result)
        # error case
        result = utils.parse_server_string('www.exa:mple.com:8443')
        self.assertEqual(('', ''), result)
        result = utils.parse_server_string('')
        self.assertEqual(('', ''), result)

    def test_hostname_unicode_sanitization(self):
        hostname = u"\u7684.test.example.com"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_periods(self):
        hostname = "....test.example.com..."
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_dashes(self):
        hostname = "----test.example.com---"
        self.assertEqual("test.example.com",
                         utils.sanitize_hostname(hostname))

    def test_hostname_sanitize_characters(self):
        hostname = "(#@&$!(@*--#&91)(__=+--test-host.example!!.com-0+"
        self.assertEqual("91----test-host.example.com-0",
                         utils.sanitize_hostname(hostname))

    def test_hostname_translate(self):
        hostname = "<}\x1fh\x10e\x08l\x02l\x05o\x12!{>"
        self.assertEqual("hello", utils.sanitize_hostname(hostname))

    def test_hostname_has_default(self):
        hostname = u"\u7684hello"
        defaultname = "Server-1"
        self.assertEqual("hello", utils.sanitize_hostname(hostname,
                                                          defaultname))

    def test_hostname_empty_has_default(self):
        hostname = u"\u7684"
        defaultname = "Server-1"
        self.assertEqual(defaultname, utils.sanitize_hostname(hostname,
                                                              defaultname))

    def test_hostname_empty_has_default_too_long(self):
        hostname = u"\u7684"
        defaultname = "a" * 64
        self.assertEqual("a" * 63, utils.sanitize_hostname(hostname,
                                                           defaultname))

    def test_hostname_empty_no_default(self):
        hostname = u"\u7684"
        self.assertEqual("", utils.sanitize_hostname(hostname))

    def test_hostname_empty_minus_period(self):
        hostname = "---..."
        self.assertEqual("", utils.sanitize_hostname(hostname))

    def test_hostname_with_space(self):
        hostname = " a b c "
        self.assertEqual("a-b-c", utils.sanitize_hostname(hostname))

    def test_hostname_too_long(self):
        hostname = "a" * 64
        self.assertEqual(63, len(utils.sanitize_hostname(hostname)))

    def test_hostname_truncated_no_hyphen(self):
        hostname = "a" * 62
        hostname = hostname + '-' + 'a'
        res = utils.sanitize_hostname(hostname)
        # we trim to 63 and then trim the trailing dash
        self.assertEqual(62, len(res))
        self.assertFalse(res.endswith('-'), 'The hostname ends with a -')

    def test_generate_password(self):
        password = utils.generate_password()
        self.assertTrue([c for c in password if c in '0123456789'])
        self.assertTrue([c for c in password
                         if c in 'abcdefghijklmnopqrstuvwxyz'])
        self.assertTrue([c for c in password
                         if c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'])

    @mock.patch('nova.privsep.path.chown')
    def test_temporary_chown(self, mock_chown):
        with tempfile.NamedTemporaryFile() as f:
            with utils.temporary_chown(f.name, owner_uid=2):
                mock_chown.assert_called_once_with(f.name, uid=2)
                mock_chown.reset_mock()
            mock_chown.assert_called_once_with(f.name, uid=os.getuid())

    def test_get_shortened_ipv6(self):
        self.assertEqual("abcd:ef01:2345:6789:abcd:ef01:c0a8:fefe",
                         utils.get_shortened_ipv6(
                            "abcd:ef01:2345:6789:abcd:ef01:192.168.254.254"))
        self.assertEqual("::1", utils.get_shortened_ipv6(
                                    "0000:0000:0000:0000:0000:0000:0000:0001"))
        self.assertEqual("caca::caca:0:babe:201:102",
                         utils.get_shortened_ipv6(
                                    "caca:0000:0000:caca:0000:babe:0201:0102"))
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError, utils.get_shortened_ipv6,
                          "failure")

    def test_get_shortened_ipv6_cidr(self):
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600:0000:0000:0000:0000:0000:0000:0000/64"))
        self.assertEqual("2600::/64", utils.get_shortened_ipv6_cidr(
                "2600::1/64"))
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "127.0.0.1")
        self.assertRaises(netaddr.AddrFormatError,
                          utils.get_shortened_ipv6_cidr,
                          "failure")

    def test_safe_ip_format(self):
        self.assertEqual("[::1]", utils.safe_ip_format("::1"))
        self.assertEqual("127.0.0.1", utils.safe_ip_format("127.0.0.1"))
        self.assertEqual("[::ffff:127.0.0.1]", utils.safe_ip_format(
                         "::ffff:127.0.0.1"))
        self.assertEqual("localhost", utils.safe_ip_format("localhost"))

    def test_format_remote_path(self):
        self.assertEqual("[::1]:/foo/bar",
                         utils.format_remote_path("::1", "/foo/bar"))
        self.assertEqual("127.0.0.1:/foo/bar",
                         utils.format_remote_path("127.0.0.1", "/foo/bar"))
        self.assertEqual("[::ffff:127.0.0.1]:/foo/bar",
                         utils.format_remote_path("::ffff:127.0.0.1",
                                                  "/foo/bar"))
        self.assertEqual("localhost:/foo/bar",
                         utils.format_remote_path("localhost", "/foo/bar"))
        self.assertEqual("/foo/bar", utils.format_remote_path(None,
                                                              "/foo/bar"))

    def test_get_hash_str(self):
        base_str = b"foo"
        base_unicode = u"foo"
        value = hashlib.md5(base_str).hexdigest()
        self.assertEqual(
            value, utils.get_hash_str(base_str))
        self.assertEqual(
            value, utils.get_hash_str(base_unicode))

    def test_get_obj_repr_unicode(self):
        instance = instance_obj.Instance()
        instance.display_name = u'\u00CD\u00F1st\u00E1\u00F1c\u00E9'
        # should be a bytes string if python2 before conversion
        self.assertIs(str, type(repr(instance)))
        self.assertIs(six.text_type,
                      type(utils.get_obj_repr_unicode(instance)))

    @mock.patch('oslo_concurrency.processutils.execute')
    def test_ssh_execute(self, mock_execute):
        expected_args = ('ssh', '-o', 'BatchMode=yes',
                         'remotehost', 'ls', '-l')
        utils.ssh_execute('remotehost', 'ls', '-l')
        mock_execute.assert_called_once_with(*expected_args)

    def test_generate_hostid(self):
        host = 'host'
        project_id = '9b9e3c847e904b0686e8ffb20e4c6381'
        hostId = 'fa123c6f74efd4aad95f84096f9e187caa0625925a9e7837b2b46792'
        self.assertEqual(hostId, utils.generate_hostid(host, project_id))

    def test_generate_hostid_with_none_host(self):
        project_id = '9b9e3c847e904b0686e8ffb20e4c6381'
        self.assertEqual('', utils.generate_hostid(None, project_id))


class TestCachedFile(test.NoDBTestCase):
    @mock.patch('os.path.getmtime', return_value=1)
    def test_read_cached_file(self, getmtime):
        utils._FILE_CACHE = {
            '/this/is/a/fake': {"data": 1123, "mtime": 1}
        }
        fresh, data = utils.read_cached_file("/this/is/a/fake")
        fdata = utils._FILE_CACHE['/this/is/a/fake']["data"]
        self.assertEqual(fdata, data)

    @mock.patch('os.path.getmtime', return_value=2)
    def test_read_modified_cached_file(self, getmtime):

        utils._FILE_CACHE = {
            '/this/is/a/fake': {"data": 1123, "mtime": 1}
        }

        fake_contents = "lorem ipsum"

        with mock.patch('six.moves.builtins.open',
                        mock.mock_open(read_data=fake_contents)):
            fresh, data = utils.read_cached_file("/this/is/a/fake")

        self.assertEqual(data, fake_contents)
        self.assertTrue(fresh)

    def test_delete_cached_file(self):
        filename = '/this/is/a/fake/deletion/of/cached/file'
        utils._FILE_CACHE = {
            filename: {"data": 1123, "mtime": 1}
        }
        self.assertIn(filename, utils._FILE_CACHE)
        utils.delete_cached_file(filename)
        self.assertNotIn(filename, utils._FILE_CACHE)

    def test_delete_cached_file_not_exist(self):
        # We expect that if cached file does not exist no Exception raised.
        filename = '/this/is/a/fake/deletion/attempt/of/not/cached/file'
        self.assertNotIn(filename, utils._FILE_CACHE)
        utils.delete_cached_file(filename)
        self.assertNotIn(filename, utils._FILE_CACHE)


class AuditPeriodTest(test.NoDBTestCase):

    def setUp(self):
        super(AuditPeriodTest, self).setUp()
        # a fairly random time to test with
        self.useFixture(utils_fixture.TimeFixture(
            datetime.datetime(second=23,
                              minute=12,
                              hour=8,
                              day=5,
                              month=3,
                              year=2012)))

    def test_hour(self):
        begin, end = utils.last_completed_audit_period(unit='hour')
        self.assertEqual(begin, datetime.datetime(
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@10')
        self.assertEqual(begin, datetime.datetime(
                                           minute=10,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           minute=10,
                                           hour=8,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_hour_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='hour@30')
        self.assertEqual(begin, datetime.datetime(
                                           minute=30,
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           minute=30,
                                           hour=7,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day(self):
        begin, end = utils.last_completed_audit_period(unit='day')
        self.assertEqual(begin, datetime.datetime(
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@6')
        self.assertEqual(begin, datetime.datetime(
                                           hour=6,
                                           day=4,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=6,
                                           day=5,
                                           month=3,
                                           year=2012))

    def test_day_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='day@10')
        self.assertEqual(begin, datetime.datetime(
                                           hour=10,
                                           day=3,
                                           month=3,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           hour=10,
                                           day=4,
                                           month=3,
                                           year=2012))

    def test_month(self):
        begin, end = utils.last_completed_audit_period(unit='month')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@2')
        self.assertEqual(begin, datetime.datetime(
                                           day=2,
                                           month=2,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=2,
                                           month=3,
                                           year=2012))

    def test_month_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='month@15')
        self.assertEqual(begin, datetime.datetime(
                                           day=15,
                                           month=1,
                                           year=2012))
        self.assertEqual(end, datetime.datetime(
                                           day=15,
                                           month=2,
                                           year=2012))

    def test_year(self):
        begin, end = utils.last_completed_audit_period(unit='year')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2011))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=1,
                                           year=2012))

    def test_year_with_offset_before_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@2')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2011))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=2,
                                           year=2012))

    def test_year_with_offset_after_current(self):
        begin, end = utils.last_completed_audit_period(unit='year@6')
        self.assertEqual(begin, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2010))
        self.assertEqual(end, datetime.datetime(
                                           day=1,
                                           month=6,
                                           year=2011))


class MetadataToDictTestCase(test.NoDBTestCase):
    def test_metadata_to_dict(self):
        self.assertEqual(utils.metadata_to_dict(
                [{'key': 'foo1', 'value': 'bar'},
                 {'key': 'foo2', 'value': 'baz'}]),
                         {'foo1': 'bar', 'foo2': 'baz'})

    def test_metadata_to_dict_with_include_deleted(self):
        metadata = [{'key': 'foo1', 'value': 'bar', 'deleted': 1442875429,
                     'other': 'stuff'},
                    {'key': 'foo2', 'value': 'baz', 'deleted': 0,
                     'other': 'stuff2'}]
        self.assertEqual({'foo1': 'bar', 'foo2': 'baz'},
                         utils.metadata_to_dict(metadata,
                                                include_deleted=True))
        self.assertEqual({'foo2': 'baz'},
                         utils.metadata_to_dict(metadata,
                                                include_deleted=False))
        # verify correct default behavior
        self.assertEqual(utils.metadata_to_dict(metadata),
                         utils.metadata_to_dict(metadata,
                                                include_deleted=False))

    def test_metadata_to_dict_empty(self):
        self.assertEqual({}, utils.metadata_to_dict([]))
        self.assertEqual({}, utils.metadata_to_dict([], include_deleted=True))
        self.assertEqual({}, utils.metadata_to_dict([], include_deleted=False))

    def test_dict_to_metadata(self):
        def sort_key(adict):
            return sorted(adict.items())

        metadata = utils.dict_to_metadata(dict(foo1='bar1', foo2='bar2'))
        expected = [{'key': 'foo1', 'value': 'bar1'},
                    {'key': 'foo2', 'value': 'bar2'}]
        self.assertEqual(sorted(metadata, key=sort_key),
                         sorted(expected, key=sort_key))

    def test_dict_to_metadata_empty(self):
        self.assertEqual(utils.dict_to_metadata({}), [])


class ExpectedArgsTestCase(test.NoDBTestCase):
    def test_passes(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        @dec
        def func(foo, bar, baz="lol"):
            pass

        # Call to ensure nothing errors
        func(None, None)

    def test_raises(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        def func(bar, baz):
            pass

        self.assertRaises(TypeError, dec, func)

    def test_var_no_of_args(self):
        @utils.expects_func_args('foo')
        def dec(f):
            return f

        @dec
        def func(bar, *args, **kwargs):
            pass

        # Call to ensure nothing errors
        func(None)

    def test_more_layers(self):
        @utils.expects_func_args('foo', 'baz')
        def dec(f):
            return f

        def dec_2(f):
            def inner_f(*a, **k):
                return f()
            return inner_f

        @dec_2
        def func(bar, baz):
            pass

        self.assertRaises(TypeError, dec, func)


class StringLengthTestCase(test.NoDBTestCase):
    def test_check_string_length(self):
        self.assertIsNone(utils.check_string_length(
                          'test', 'name', max_length=255))
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          11, 'name', max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          '', 'name', min_length=1)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, 'name', max_length=255)

    def test_check_string_length_noname(self):
        self.assertIsNone(utils.check_string_length(
                          'test', max_length=255))
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          11, max_length=255)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          '', min_length=1)
        self.assertRaises(exception.InvalidInput,
                          utils.check_string_length,
                          'a' * 256, max_length=255)


class ValidateIntegerTestCase(test.NoDBTestCase):
    def test_exception_converted(self):
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          "im-not-an-int", "not-an-int")
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          3.14, "Pie")
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          "299", "Sparta no-show",
                          min_value=300, max_value=300)
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          55, "doing 55 in a 54",
                          max_value=54)
        self.assertRaises(exception.InvalidInput,
                          utils.validate_integer,
                          six.unichr(129), "UnicodeError",
                          max_value=1000)


class ValidateNeutronConfiguration(test.NoDBTestCase):
    def test_nova_network(self):
        self.flags(use_neutron=False)
        self.assertFalse(utils.is_neutron())

    def test_neutron(self):
        self.flags(use_neutron=True)
        self.assertTrue(utils.is_neutron())


class AutoDiskConfigUtilTestCase(test.NoDBTestCase):
    def test_is_auto_disk_config_disabled(self):
        self.assertTrue(utils.is_auto_disk_config_disabled("Disabled "))

    def test_is_auto_disk_config_disabled_none(self):
        self.assertFalse(utils.is_auto_disk_config_disabled(None))

    def test_is_auto_disk_config_disabled_false(self):
        self.assertFalse(utils.is_auto_disk_config_disabled("false"))


class GetSystemMetadataFromImageTestCase(test.NoDBTestCase):
    def get_image(self):
        image_meta = {
            "id": "fake-image",
            "name": "fake-name",
            "min_ram": 1,
            "min_disk": 1,
            "disk_format": "raw",
            "container_format": "bare",
        }

        return image_meta

    def get_flavor(self):
        flavor = {
            "id": "fake.flavor",
            "root_gb": 10,
        }

        return flavor

    def test_base_image_properties(self):
        image = self.get_image()

        # Verify that we inherit all the needed keys
        sys_meta = utils.get_system_metadata_from_image(image)
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image[key], sys_meta.get(sys_key))

        # Verify that everything else is ignored
        self.assertEqual(len(sys_meta), len(utils.SM_INHERITABLE_KEYS))

    def test_inherit_image_properties(self):
        image = self.get_image()
        image["properties"] = {"foo1": "bar", "foo2": "baz"}

        sys_meta = utils.get_system_metadata_from_image(image)

        # Verify that we inherit all the image properties
        for key, expected in image["properties"].items():
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(sys_meta[sys_key], expected)

    def test_skip_image_properties(self):
        image = self.get_image()
        image["properties"] = {
            "foo1": "bar", "foo2": "baz",
            "mappings": "wizz", "img_block_device_mapping": "eek",
        }

        sys_meta = utils.get_system_metadata_from_image(image)

        # Verify that we inherit all the image properties
        for key, expected in image["properties"].items():
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)

            if key in utils.SM_SKIP_KEYS:
                self.assertNotIn(sys_key, sys_meta)
            else:
                self.assertEqual(sys_meta[sys_key], expected)

    def test_vhd_min_disk_image(self):
        image = self.get_image()
        flavor = self.get_flavor()

        image["disk_format"] = "vhd"

        sys_meta = utils.get_system_metadata_from_image(image, flavor)

        # Verify that the min_disk property is taken from
        # flavor's root_gb when using vhd disk format
        sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, "min_disk")
        self.assertEqual(sys_meta[sys_key], flavor["root_gb"])

    def test_dont_inherit_empty_values(self):
        image = self.get_image()

        for key in utils.SM_INHERITABLE_KEYS:
            image[key] = None

        sys_meta = utils.get_system_metadata_from_image(image)

        # Verify that the empty properties have not been inherited
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertNotIn(sys_key, sys_meta)


class GetImageFromSystemMetadataTestCase(test.NoDBTestCase):
    def get_system_metadata(self):
        sys_meta = {
            "image_min_ram": 1,
            "image_min_disk": 1,
            "image_disk_format": "raw",
            "image_container_format": "bare",
        }

        return sys_meta

    def test_image_from_system_metadata(self):
        sys_meta = self.get_system_metadata()
        sys_meta["%soo1" % utils.SM_IMAGE_PROP_PREFIX] = "bar"
        sys_meta["%soo2" % utils.SM_IMAGE_PROP_PREFIX] = "baz"
        sys_meta["%simg_block_device_mapping" %
                 utils.SM_IMAGE_PROP_PREFIX] = "eek"

        image = utils.get_image_from_system_metadata(sys_meta)

        # Verify that we inherit all the needed keys
        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image[key], sys_meta.get(sys_key))

        # Verify that we inherit the rest of metadata as properties
        self.assertIn("properties", image)

        for key in image["properties"]:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            self.assertEqual(image["properties"][key], sys_meta[sys_key])

        self.assertNotIn("img_block_device_mapping", image["properties"])

    def test_dont_inherit_empty_values(self):
        sys_meta = self.get_system_metadata()

        for key in utils.SM_INHERITABLE_KEYS:
            sys_key = "%s%s" % (utils.SM_IMAGE_PROP_PREFIX, key)
            sys_meta[sys_key] = None

        image = utils.get_image_from_system_metadata(sys_meta)

        # Verify that the empty properties have not been inherited
        for key in utils.SM_INHERITABLE_KEYS:
            self.assertNotIn(key, image)


class GetImageMetadataFromVolumeTestCase(test.NoDBTestCase):
    def test_inherit_image_properties(self):
        properties = {"fake_prop": "fake_value"}
        volume = {"volume_image_metadata": properties}
        image_meta = utils.get_image_metadata_from_volume(volume)
        self.assertEqual(properties, image_meta["properties"])

    def test_image_size(self):
        volume = {"size": 10}
        image_meta = utils.get_image_metadata_from_volume(volume)
        self.assertEqual(10 * units.Gi, image_meta["size"])

    def test_image_status(self):
        volume = {}
        image_meta = utils.get_image_metadata_from_volume(volume)
        self.assertEqual("active", image_meta["status"])

    def test_values_conversion(self):
        properties = {"min_ram": "5", "min_disk": "7"}
        volume = {"volume_image_metadata": properties}
        image_meta = utils.get_image_metadata_from_volume(volume)
        self.assertEqual(5, image_meta["min_ram"])
        self.assertEqual(7, image_meta["min_disk"])

    def test_suppress_not_image_properties(self):
        properties = {"min_ram": "256", "min_disk": "128",
                      "image_id": "fake_id", "image_name": "fake_name",
                      "container_format": "ami", "disk_format": "ami",
                      "size": "1234", "checksum": "fake_checksum"}
        volume = {"volume_image_metadata": properties}
        image_meta = utils.get_image_metadata_from_volume(volume)
        self.assertEqual({}, image_meta["properties"])
        self.assertEqual(0, image_meta["size"])
        # volume's properties should not be touched
        self.assertNotEqual({}, properties)


class SafeTruncateTestCase(test.NoDBTestCase):
    def test_exception_to_dict_with_long_message_3_bytes(self):
        # Generate Chinese byte string whose length is 300. This Chinese UTF-8
        # character occupies 3 bytes. After truncating, the byte string length
        # should be 255.
        msg = u'\u8d75' * 100
        truncated_msg = utils.safe_truncate(msg, 255)
        byte_message = encodeutils.safe_encode(truncated_msg)
        self.assertEqual(255, len(byte_message))

    def test_exception_to_dict_with_long_message_2_bytes(self):
        # Generate Russian byte string whose length is 300. This Russian UTF-8
        # character occupies 2 bytes. After truncating, the byte string length
        # should be 254.
        msg = encodeutils.safe_decode('\xd0\x92' * 150)
        truncated_msg = utils.safe_truncate(msg, 255)
        byte_message = encodeutils.safe_encode(truncated_msg)
        self.assertEqual(254, len(byte_message))


class SpawnNTestCase(test.NoDBTestCase):
    def setUp(self):
        super(SpawnNTestCase, self).setUp()
        self.useFixture(context_fixture.ClearRequestContext())
        self.spawn_name = 'spawn_n'

    def test_spawn_n_no_context(self):
        self.assertIsNone(common_context.get_current())

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual('test', args[0])

        def fake(arg):
            pass

        with mock.patch.object(eventlet, self.spawn_name, _fake_spawn):
            getattr(utils, self.spawn_name)(fake, 'test')
        self.assertIsNone(common_context.get_current())

    def test_spawn_n_context(self):
        self.assertIsNone(common_context.get_current())
        ctxt = context.RequestContext('user', 'project')

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual(ctxt, args[0])
            self.assertEqual('test', kwargs['kwarg1'])

        def fake(context, kwarg1=None):
            pass

        with mock.patch.object(eventlet, self.spawn_name, _fake_spawn):
            getattr(utils, self.spawn_name)(fake, ctxt, kwarg1='test')
        self.assertEqual(ctxt, common_context.get_current())

    def test_spawn_n_context_different_from_passed(self):
        self.assertIsNone(common_context.get_current())
        ctxt = context.RequestContext('user', 'project')
        ctxt_passed = context.RequestContext('user', 'project',
                overwrite=False)
        self.assertEqual(ctxt, common_context.get_current())

        def _fake_spawn(func, *args, **kwargs):
            # call the method to ensure no error is raised
            func(*args, **kwargs)
            self.assertEqual(ctxt_passed, args[0])
            self.assertEqual('test', kwargs['kwarg1'])

        def fake(context, kwarg1=None):
            pass

        with mock.patch.object(eventlet, self.spawn_name, _fake_spawn):
            getattr(utils, self.spawn_name)(fake, ctxt_passed, kwarg1='test')
        self.assertEqual(ctxt, common_context.get_current())


class SpawnTestCase(SpawnNTestCase):
    def setUp(self):
        super(SpawnTestCase, self).setUp()
        self.spawn_name = 'spawn'


class UT8TestCase(test.NoDBTestCase):
    def test_none_value(self):
        self.assertIsInstance(utils.utf8(None), type(None))

    def test_bytes_value(self):
        some_value = b"fake data"
        return_value = utils.utf8(some_value)
        # check that type of returned value doesn't changed
        self.assertIsInstance(return_value, type(some_value))
        self.assertEqual(some_value, return_value)

    def test_not_text_type(self):
        return_value = utils.utf8(1)
        self.assertEqual(b"1", return_value)
        self.assertIsInstance(return_value, six.binary_type)

    def test_text_type_with_encoding(self):
        some_value = 'test\u2026config'
        self.assertEqual(some_value, utils.utf8(some_value).decode("utf-8"))


class TestObjectCallHelpers(test.NoDBTestCase):
    def test_with_primitives(self):
        tester = mock.Mock()
        tester.foo(1, 'two', three='four')
        self.assertTrue(
            test_utils.obj_called_with(tester.foo, 1, 'two', three='four'))
        self.assertFalse(
            test_utils.obj_called_with(tester.foo, 42, 'two', three='four'))

    def test_with_object(self):
        obj_base.NovaObjectRegistry.register(test_objects.MyObj)
        obj = test_objects.MyObj(foo=1, bar='baz')
        tester = mock.Mock()
        tester.foo(1, obj)
        self.assertTrue(
            test_utils.obj_called_with(
                tester.foo, 1,
                test_objects.MyObj(foo=1, bar='baz')))
        self.assertFalse(
            test_utils.obj_called_with(
                tester.foo, 1,
                test_objects.MyObj(foo=2, bar='baz')))

    def test_with_object_multiple(self):
        obj_base.NovaObjectRegistry.register(test_objects.MyObj)
        obj1 = test_objects.MyObj(foo=1, bar='baz')
        obj2 = test_objects.MyObj(foo=3, bar='baz')
        tester = mock.Mock()
        tester.foo(1, obj1)
        tester.foo(1, obj1)
        tester.foo(3, obj2)

        # Called at all
        self.assertTrue(
            test_utils.obj_called_with(
                tester.foo, 1,
                test_objects.MyObj(foo=1, bar='baz')))

        # Called once (not true)
        self.assertFalse(
            test_utils.obj_called_once_with(
                tester.foo, 1,
                test_objects.MyObj(foo=1, bar='baz')))

        # Not called with obj.foo=2
        self.assertFalse(
            test_utils.obj_called_with(
                tester.foo, 1,
                test_objects.MyObj(foo=2, bar='baz')))

        # Called with obj.foo.3
        self.assertTrue(
            test_utils.obj_called_with(
                tester.foo, 3,
                test_objects.MyObj(foo=3, bar='baz')))

        # Called once with obj.foo.3
        self.assertTrue(
            test_utils.obj_called_once_with(
                tester.foo, 3,
                test_objects.MyObj(foo=3, bar='baz')))


class GetKSAAdapterTestCase(test.NoDBTestCase):
    """Tests for nova.utils.get_endpoint_data()."""
    def setUp(self):
        super(GetKSAAdapterTestCase, self).setUp()
        self.sess = mock.create_autospec(ks_session.Session, instance=True)
        self.auth = mock.create_autospec(ks_identity.BaseIdentityPlugin,
                                         instance=True)

        load_adap_p = mock.patch(
            'keystoneauth1.loading.load_adapter_from_conf_options')
        self.addCleanup(load_adap_p.stop)
        self.load_adap = load_adap_p.start()

        ksa_fixture = self.useFixture(nova_fixtures.KSAFixture())
        self.mock_ksa_load_auth = ksa_fixture.mock_load_auth
        self.mock_ksa_load_sess = ksa_fixture.mock_load_sess
        self.mock_ksa_session = ksa_fixture.mock_session

        self.mock_ksa_load_auth.return_value = self.auth
        self.mock_ksa_load_sess.return_value = self.sess

    def test_bogus_service_type(self):
        self.assertRaises(exception.ConfGroupForServiceTypeNotFound,
                          utils.get_ksa_adapter, 'bogus')
        self.mock_ksa_load_auth.assert_not_called()
        self.mock_ksa_load_sess.assert_not_called()
        self.load_adap.assert_not_called()

    def test_all_params(self):
        ret = utils.get_ksa_adapter(
            'image', ksa_auth='auth', ksa_session='sess',
            min_version='min', max_version='max')
        # Returned the result of load_adapter_from_conf_options
        self.assertEqual(self.load_adap.return_value, ret)
        # Because we supplied ksa_auth, load_auth* not called
        self.mock_ksa_load_auth.assert_not_called()
        # Ditto ksa_session/load_session*
        self.mock_ksa_load_sess.assert_not_called()
        # load_adapter* called with what we passed in (and the right group)
        self.load_adap.assert_called_once_with(
            utils.CONF, 'glance', session='sess', auth='auth',
            min_version='min', max_version='max', raise_exc=False)

    def test_auth_from_session(self):
        self.sess.auth = 'auth'
        ret = utils.get_ksa_adapter('baremetal', ksa_session=self.sess)
        # Returned the result of load_adapter_from_conf_options
        self.assertEqual(self.load_adap.return_value, ret)
        # Because ksa_auth found in ksa_session, load_auth* not called
        self.mock_ksa_load_auth.assert_not_called()
        # Because we supplied ksa_session, load_session* not called
        self.mock_ksa_load_sess.assert_not_called()
        # load_adapter* called with the auth from the session
        self.load_adap.assert_called_once_with(
            utils.CONF, 'ironic', session=self.sess, auth='auth',
            min_version=None, max_version=None, raise_exc=False)

    def test_load_auth_and_session(self):
        ret = utils.get_ksa_adapter('volumev3')
        # Returned the result of load_adapter_from_conf_options
        self.assertEqual(self.load_adap.return_value, ret)
        # Had to load the auth
        self.mock_ksa_load_auth.assert_called_once_with(utils.CONF, 'cinder')
        # Had to load the session, passed in the loaded auth
        self.mock_ksa_load_sess.assert_called_once_with(utils.CONF, 'cinder',
                                                        auth=self.auth)
        # load_adapter* called with the loaded auth & session
        self.load_adap.assert_called_once_with(
            utils.CONF, 'cinder', session=self.sess, auth=self.auth,
            min_version=None, max_version=None, raise_exc=False)


class GetEndpointTestCase(test.NoDBTestCase):
    def setUp(self):
        super(GetEndpointTestCase, self).setUp()
        self.adap = mock.create_autospec(ks_adapter.Adapter, instance=True)
        self.adap.endpoint_override = None
        self.adap.service_type = 'stype'
        self.adap.interface = ['admin', 'public']

    def test_endpoint_override(self):
        self.adap.endpoint_override = 'foo'
        self.assertEqual('foo', utils.get_endpoint(self.adap))
        self.adap.get_endpoint_data.assert_not_called()
        self.adap.get_endpoint.assert_not_called()

    def test_image_good(self):
        self.adap.service_type = 'image'
        self.adap.get_endpoint_data.return_value.catalog_url = 'url'
        self.assertEqual('url', utils.get_endpoint(self.adap))
        self.adap.get_endpoint_data.assert_called_once_with()
        self.adap.get_endpoint.assert_not_called()

    def test_image_bad(self):
        self.adap.service_type = 'image'
        self.adap.get_endpoint_data.side_effect = AttributeError
        self.adap.get_endpoint.return_value = 'url'
        self.assertEqual('url', utils.get_endpoint(self.adap))
        self.adap.get_endpoint_data.assert_called_once_with()
        self.adap.get_endpoint.assert_called_once_with()

    def test_nonimage_good(self):
        self.adap.get_endpoint.return_value = 'url'
        self.assertEqual('url', utils.get_endpoint(self.adap))
        self.adap.get_endpoint_data.assert_not_called()
        self.adap.get_endpoint.assert_called_once_with()

    def test_nonimage_try_interfaces(self):
        self.adap.get_endpoint.side_effect = (ks_exc.EndpointNotFound, 'url')
        self.assertEqual('url', utils.get_endpoint(self.adap))
        self.adap.get_endpoint_data.assert_not_called()
        self.assertEqual(2, self.adap.get_endpoint.call_count)
        self.assertEqual('admin', self.adap.interface)

    def test_nonimage_try_interfaces_fail(self):
        self.adap.get_endpoint.side_effect = ks_exc.EndpointNotFound
        self.assertRaises(ks_exc.EndpointNotFound,
                          utils.get_endpoint, self.adap)
        self.adap.get_endpoint_data.assert_not_called()
        self.assertEqual(3, self.adap.get_endpoint.call_count)
        self.assertEqual('public', self.adap.interface)


class RunOnceTests(test.NoDBTestCase):

    fake_logger = mock.MagicMock()

    @utils.run_once("already ran once", fake_logger)
    def dummy_test_func(self, fail=False):
        if fail:
            raise ValueError()
        return True

    def setUp(self):
        super(RunOnceTests, self).setUp()
        self.dummy_test_func.reset()
        RunOnceTests.fake_logger.reset_mock()

    def test_wrapped_funtions_called_once(self):
        self.assertFalse(self.dummy_test_func.called)
        result = self.dummy_test_func()
        self.assertTrue(result)
        self.assertTrue(self.dummy_test_func.called)

        # assert that on second invocation no result
        # is returned and that the logger is invoked.
        result = self.dummy_test_func()
        RunOnceTests.fake_logger.assert_called_once()
        self.assertIsNone(result)

    def test_wrapped_funtions_called_once_raises(self):
        self.assertFalse(self.dummy_test_func.called)
        self.assertRaises(ValueError, self.dummy_test_func, fail=True)
        self.assertTrue(self.dummy_test_func.called)

        # assert that on second invocation no result
        # is returned and that the logger is invoked.
        result = self.dummy_test_func()
        RunOnceTests.fake_logger.assert_called_once()
        self.assertIsNone(result)

    def test_wrapped_funtions_can_be_reset(self):
        # assert we start with a clean state
        self.assertFalse(self.dummy_test_func.called)
        result = self.dummy_test_func()
        self.assertTrue(result)

        self.dummy_test_func.reset()
        # assert we restored a clean state
        self.assertFalse(self.dummy_test_func.called)
        result = self.dummy_test_func()
        self.assertTrue(result)

        # assert that we never called the logger
        RunOnceTests.fake_logger.assert_not_called()

    def test_reset_calls_cleanup(self):
        mock_clean = mock.Mock()

        @utils.run_once("already ran once", self.fake_logger,
                        cleanup=mock_clean)
        def f():
            pass

        f()
        self.assertTrue(f.called)

        f.reset()
        self.assertFalse(f.called)
        mock_clean.assert_called_once_with()

    def test_clean_is_not_called_at_reset_if_wrapped_not_called(self):
        mock_clean = mock.Mock()

        @utils.run_once("already ran once", self.fake_logger,
                        cleanup=mock_clean)
        def f():
            pass

        self.assertFalse(f.called)

        f.reset()
        self.assertFalse(f.called)
        self.assertFalse(mock_clean.called)

    def test_reset_works_even_if_cleanup_raises(self):
        mock_clean = mock.Mock(side_effect=ValueError())

        @utils.run_once("already ran once", self.fake_logger,
                        cleanup=mock_clean)
        def f():
            pass

        f()
        self.assertTrue(f.called)

        self.assertRaises(ValueError, f.reset)
        self.assertFalse(f.called)
        mock_clean.assert_called_once_with()


class TestResourceClassNormalize(test.NoDBTestCase):

    def test_normalize_name(self):
        values = [
            ("foo", "CUSTOM_FOO"),
            ("VCPU", "CUSTOM_VCPU"),
            ("CUSTOM_BOB", "CUSTOM_CUSTOM_BOB"),
            ("CUSTM_BOB", "CUSTOM_CUSTM_BOB"),
        ]
        for test_value, expected in values:
            result = utils.normalize_rc_name(test_value)
            self.assertEqual(expected, result)

    def test_normalize_name_bug_1762789(self):
        """The .upper() builtin treats sharp S (\xdf) differently in py2 vs.
        py3.  Make sure normalize_name handles it properly.
        """
        name = u'Fu\xdfball'
        self.assertEqual(u'CUSTOM_FU_BALL', utils.normalize_rc_name(name))


class TestGetConfGroup(test.NoDBTestCase):
    """Tests for nova.utils._get_conf_group"""
    @mock.patch('nova.utils.CONF')
    @mock.patch('nova.utils._SERVICE_TYPES.get_project_name')
    def test__get_conf_group(self, mock_get_project_name, mock_conf):
        test_conf_grp = 'test_confgrp'
        test_service_type = 'test_service_type'
        mock_get_project_name.return_value = test_conf_grp

        # happy path
        mock_conf.test_confgrp = None
        actual_conf_grp = utils._get_conf_group(test_service_type)
        self.assertEqual(test_conf_grp, actual_conf_grp)
        mock_get_project_name.assert_called_once_with(test_service_type)

        # service type as the conf group
        del mock_conf.test_confgrp
        mock_conf.test_service_type = None
        actual_conf_grp = utils._get_conf_group(test_service_type)
        self.assertEqual(test_service_type, actual_conf_grp)

    @mock.patch('nova.utils._SERVICE_TYPES.get_project_name')
    def test__get_conf_group_fail(self, mock_get_project_name):
        test_service_type = 'test_service_type'

        # not confgrp
        mock_get_project_name.return_value = None
        self.assertRaises(exception.ConfGroupForServiceTypeNotFound,
                          utils._get_conf_group, None)

        # not hasattr
        mock_get_project_name.return_value = 'test_fail'
        self.assertRaises(exception.ConfGroupForServiceTypeNotFound,
                          utils._get_conf_group, test_service_type)


class TestGetAuthAndSession(test.NoDBTestCase):
    """Tests for nova.utils._get_auth_and_session"""
    def setUp(self):
        super(TestGetAuthAndSession, self).setUp()

        self.test_auth = 'test_auth'
        self.test_session = 'test_session'
        self.test_session_auth = 'test_session_auth'
        self.test_confgrp = 'test_confgrp'
        self.mock_session = mock.Mock()
        self.mock_session.auth = self.test_session_auth

    @mock.patch('nova.utils.ks_loading.load_auth_from_conf_options')
    @mock.patch('nova.utils.ks_loading.load_session_from_conf_options')
    def test_auth_and_session(self, mock_load_session, mock_load_auth):
        # yes auth, yes session
        actual = utils._get_auth_and_session(self.test_confgrp,
                                             ksa_auth=self.test_auth,
                                             ksa_session=self.test_session)
        self.assertEqual(actual, (self.test_auth, self.test_session))
        mock_load_session.assert_not_called()
        mock_load_auth.assert_not_called()

    @mock.patch('nova.utils.ks_loading.load_auth_from_conf_options')
    @mock.patch('nova.utils.ks_loading.load_session_from_conf_options')
    @mock.patch('nova.utils.CONF')
    def test_no_session(self, mock_CONF, mock_load_session, mock_load_auth):
        # yes auth, no session
        mock_load_session.return_value = self.test_session

        actual = utils._get_auth_and_session(self.test_confgrp,
                                             ksa_auth=self.test_auth,
                                             ksa_session=None)

        self.assertEqual(actual, (self.test_auth, self.test_session))
        mock_load_session.assert_called_once_with(mock_CONF, self.test_confgrp,
                                                  auth=self.test_auth)
        mock_load_auth.assert_not_called()

    @mock.patch('nova.utils.ks_loading.load_auth_from_conf_options')
    @mock.patch('nova.utils.ks_loading.load_session_from_conf_options')
    def test_no_auth(self, mock_load_session, mock_load_auth):
        # no auth, yes session, yes session.auth
        actual = utils._get_auth_and_session(self.test_confgrp, ksa_auth=None,
                                             ksa_session=self.mock_session)
        self.assertEqual(actual, (self.test_session_auth, self.mock_session))
        mock_load_session.assert_not_called()
        mock_load_auth.assert_not_called()

    @mock.patch('nova.utils.ks_loading.load_auth_from_conf_options')
    @mock.patch('nova.utils.ks_loading.load_session_from_conf_options')
    @mock.patch('nova.utils.CONF')
    def test_no_auth_no_sauth(self, mock_CONF, mock_load_session,
                              mock_load_auth):
        # no auth, yes session, no session.auth
        mock_load_auth.return_value = self.test_auth
        self.mock_session.auth = None
        actual = utils._get_auth_and_session(self.test_confgrp, ksa_auth=None,
                                             ksa_session=self.mock_session)
        self.assertEqual(actual, (self.test_auth, self.mock_session))
        mock_load_session.assert_not_called()
        mock_load_auth.assert_called_once_with(mock_CONF, self.test_confgrp)

    @mock.patch('nova.utils.ks_loading.load_auth_from_conf_options')
    @mock.patch('nova.utils.ks_loading.load_session_from_conf_options')
    @mock.patch('nova.utils.CONF')
    def test__get_auth_and_session(self, mock_CONF, mock_load_session,
                                   mock_load_auth):
        # no auth, no session
        mock_load_auth.return_value = self.test_auth
        mock_load_session.return_value = self.test_session
        actual = utils._get_auth_and_session(self.test_confgrp, ksa_auth=None,
                                             ksa_session=None)
        self.assertEqual(actual, (self.test_auth, self.test_session))
        mock_load_session.assert_called_once_with(mock_CONF, self.test_confgrp,
                                                  auth=self.test_auth)
        mock_load_auth.assert_called_once_with(mock_CONF, self.test_confgrp)


class TestGetSDKAdapter(test.NoDBTestCase):
    """Tests for nova.utils.get_sdk_adapter"""

    def setUp(self):
        super(TestGetSDKAdapter, self).setUp()

        self.mock_get_confgrp = self.useFixture(fixtures.MockPatch(
            'nova.utils._get_conf_group')).mock

        self.mock_get_auth_sess = self.useFixture(fixtures.MockPatch(
            'nova.utils._get_auth_and_session')).mock
        self.mock_get_auth_sess.return_value = (None, mock.sentinel.session)

        self.service_type = 'test_service'
        self.mock_connection = self.useFixture(fixtures.MockPatch(
            'nova.utils.connection.Connection')).mock
        self.mock_connection.return_value = mock.Mock(
            test_service=mock.sentinel.proxy)

        # We need to stub the CONF global in nova.utils to assert that the
        # Connection constructor picks it up.
        self.mock_conf = self.useFixture(fixtures.MockPatch(
            'nova.utils.CONF')).mock

    def _test_get_sdk_adapter(self, strict=False):
        actual = utils.get_sdk_adapter(self.service_type, check_service=strict)

        self.mock_get_confgrp.assert_called_once_with(self.service_type)
        self.mock_get_auth_sess.assert_called_once_with(
            self.mock_get_confgrp.return_value)
        self.mock_connection.assert_called_once_with(
            session=mock.sentinel.session, oslo_conf=self.mock_conf,
            service_types={'test_service'}, strict_proxies=strict)

        return actual

    def test_get_sdk_adapter(self):
        self.assertEqual(self._test_get_sdk_adapter(), mock.sentinel.proxy)

    def test_get_sdk_adapter_strict(self):
        self.assertEqual(
            self._test_get_sdk_adapter(strict=True), mock.sentinel.proxy)

    def test_get_sdk_adapter_strict_fail(self):
        self.mock_connection.side_effect = sdk_exc.ServiceDiscoveryException()
        self.assertRaises(
            exception.ServiceUnavailable,
            self._test_get_sdk_adapter, strict=True)

    def test_get_sdk_adapter_conf_group_fail(self):
        self.mock_get_confgrp.side_effect = (
            exception.ConfGroupForServiceTypeNotFound(stype=self.service_type))

        self.assertRaises(exception.ConfGroupForServiceTypeNotFound,
                          utils.get_sdk_adapter, self.service_type)
        self.mock_get_confgrp.assert_called_once_with(self.service_type)
        self.mock_connection.assert_not_called()
        self.mock_get_auth_sess.assert_not_called()
