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
import importlib
import os
import os.path
import socket
import struct
import tempfile

import eventlet
import mock
import netaddr
from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_context import context as common_context
from oslo_context import fixture as context_fixture
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import fixture as utils_fixture
from oslo_utils import units
import six

import nova
from nova import context
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova import test
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

    def test_read_file_as_root(self):
        def fake_execute(*args, **kwargs):
            if args[1] == 'bad':
                raise processutils.ProcessExecutionError()
            return 'fakecontents', None

        self.stub_out('nova.utils.execute', fake_execute)
        contents = utils.read_file_as_root('good')
        self.assertEqual(contents, 'fakecontents')
        self.assertRaises(exception.FileNotFound,
                          utils.read_file_as_root, 'bad')

    def test_temporary_chown(self):
        def fake_execute(*args, **kwargs):
            if args[0] == 'chown':
                fake_execute.uid = args[1]
        self.stub_out('nova.utils.execute', fake_execute)

        with tempfile.NamedTemporaryFile() as f:
            with utils.temporary_chown(f.name, owner_uid=2):
                self.assertEqual(fake_execute.uid, 2)
            self.assertEqual(fake_execute.uid, os.getuid())

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

    def test_use_rootwrap(self):
        self.flags(disable_rootwrap=False, group='workarounds')
        self.flags(rootwrap_config='foo')
        cmd = utils.get_root_helper()
        self.assertEqual('sudo nova-rootwrap foo', cmd)

    def test_use_sudo(self):
        self.flags(disable_rootwrap=True, group='workarounds')
        cmd = utils.get_root_helper()
        self.assertEqual('sudo', cmd)

    def test_ssh_execute(self):
        expected_args = ('ssh', '-o', 'BatchMode=yes',
                         'remotehost', 'ls', '-l')
        with mock.patch('nova.utils.execute') as mock_method:
            utils.ssh_execute('remotehost', 'ls', '-l')
        mock_method.assert_called_once_with(*expected_args)


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


class RootwrapDaemonTesetCase(test.NoDBTestCase):
    @mock.patch('oslo_rootwrap.client.Client')
    def test_get_client(self, mock_client):
        mock_conf = mock.MagicMock()
        utils.RootwrapDaemonHelper(mock_conf)
        mock_client.assert_called_once_with(
            ["sudo", "nova-rootwrap-daemon", mock_conf])

    @mock.patch('nova.utils.LOG.info')
    def test_execute(self, mock_info):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(0, None, None))

        daemon.execute('a', 1, foo='bar', run_as_root=True)
        daemon.client.execute.assert_called_once_with(['a', '1'], None)
        mock_info.assert_has_calls([mock.call(
            u'Executing RootwrapDaemonHelper.execute cmd=[%(cmd)r] '
            u'kwargs=[%(kwargs)r]',
            {'cmd': u'a 1', 'kwargs': {'run_as_root': True, 'foo': 'bar'}})])

    def test_execute_with_kwargs(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(0, None, None))

        daemon.execute('a', 1, foo='bar', run_as_root=True, process_input=True)
        daemon.client.execute.assert_called_once_with(['a', '1'], True)

    def test_execute_fail(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))

        self.assertRaises(processutils.ProcessExecutionError,
                          daemon.execute, 'b', 2)

    def test_execute_pass_with_check_exit_code(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))
        daemon.execute('b', 2, check_exit_code=[-2])

    def test_execute_fail_with_retry(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))

        self.assertRaises(processutils.ProcessExecutionError,
                          daemon.execute, 'b', 2, attempts=2)
        daemon.client.execute.assert_has_calls(
            [mock.call(['b', '2'], None),
             mock.call(['b', '2'], None)])

    @mock.patch('nova.utils.LOG.log')
    def test_execute_fail_and_logging(self, mock_log):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))

        self.assertRaises(processutils.ProcessExecutionError,
                          daemon.execute, 'b', 2,
                          attempts=2,
                          loglevel=logging.CRITICAL,
                          log_errors=processutils.LOG_ALL_ERRORS)
        mock_log.assert_has_calls(
            [
                mock.call(logging.CRITICAL, u'Running cmd (subprocess): %s',
                          u'b 2'),
                mock.call(logging.CRITICAL,
                          'CMD "%(sanitized_cmd)s" returned: %(return_code)s '
                          'in %(end_time)0.3fs',
                          {'sanitized_cmd': u'b 2', 'return_code': -2,
                           'end_time': mock.ANY}),
                mock.call(logging.CRITICAL,
                          u'%(desc)r\ncommand: %(cmd)r\nexit code: %(code)r'
                          u'\nstdout: %(stdout)r\nstderr: %(stderr)r',
                          {'code': -2, 'cmd': u'b 2', 'stdout': u'None',
                           'stderr': u'None', 'desc': None}),
                mock.call(logging.CRITICAL, u'%r failed. Retrying.', u'b 2'),
                mock.call(logging.CRITICAL, u'Running cmd (subprocess): %s',
                          u'b 2'),
                mock.call(logging.CRITICAL,
                          'CMD "%(sanitized_cmd)s" returned: %(return_code)s '
                          'in %(end_time)0.3fs',
                          {'sanitized_cmd': u'b 2', 'return_code': -2,
                           'end_time': mock.ANY}),
                mock.call(logging.CRITICAL,
                          u'%(desc)r\ncommand: %(cmd)r\nexit code: %(code)r'
                          u'\nstdout: %(stdout)r\nstderr: %(stderr)r',
                          {'code': -2, 'cmd': u'b 2', 'stdout': u'None',
                           'stderr': u'None', 'desc': None}),
                mock.call(logging.CRITICAL, u'%r failed. Not Retrying.',
                          u'b 2')]
        )

    def test_trycmd(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(0, None, None))

        daemon.trycmd('a', 1, foo='bar', run_as_root=True)
        daemon.client.execute.assert_called_once_with(['a', '1'], None)

    def test_trycmd_with_kwargs(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.execute = mock.Mock(return_value=('out', 'err'))

        daemon.trycmd('a', 1, foo='bar', run_as_root=True,
                      loglevel=logging.WARN,
                      log_errors=True,
                      process_input=True,
                      delay_on_retry=False,
                      attempts=5,
                      check_exit_code=[200])
        daemon.execute.assert_called_once_with('a', 1, attempts=5,
                                               check_exit_code=[200],
                                               delay_on_retry=False, foo='bar',
                                               log_errors=True, loglevel=30,
                                               process_input=True,
                                               run_as_root=True)

    def test_trycmd_fail(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))

        expected_err = six.text_type('''\
Unexpected error while running command.
Command: a 1
Exit code: -2''')

        out, err = daemon.trycmd('a', 1, foo='bar', run_as_root=True)
        daemon.client.execute.assert_called_once_with(['a', '1'], None)
        self.assertIn(expected_err, err)

    def test_trycmd_fail_with_rety(self):
        mock_conf = mock.MagicMock()
        daemon = utils.RootwrapDaemonHelper(mock_conf)
        daemon.client = mock.MagicMock()
        daemon.client.execute = mock.Mock(return_value=(-2, None, None))

        expected_err = six.text_type('''\
Unexpected error while running command.
Command: a 1
Exit code: -2''')

        out, err = daemon.trycmd('a', 1, foo='bar', run_as_root=True,
                                 attempts=3)
        self.assertIn(expected_err, err)
        daemon.client.execute.assert_has_calls(
            [mock.call(['a', '1'], None),
             mock.call(['a', '1'], None),
             mock.call(['a', '1'], None)])


class VPNPingTestCase(test.NoDBTestCase):
    """Unit tests for utils.vpn_ping()."""
    def setUp(self):
        super(VPNPingTestCase, self).setUp()
        self.port = 'fake'
        self.address = 'fake'
        self.session_id = 0x1234
        self.fmt = '!BQxxxxxQxxxx'

    def fake_reply_packet(self, pkt_id=0x40):
        return struct.pack(self.fmt, pkt_id, 0x0, self.session_id)

    def setup_socket(self, mock_socket, return_value, side_effect=None):
        socket_obj = mock.MagicMock()
        if side_effect is not None:
            socket_obj.recv.side_effect = side_effect
        else:
            socket_obj.recv.return_value = return_value
        mock_socket.return_value = socket_obj

    @mock.patch.object(socket, 'socket')
    def test_vpn_ping_timeout(self, mock_socket):
        """Server doesn't reply within timeout."""
        self.setup_socket(mock_socket, None, socket.timeout)
        rc = utils.vpn_ping(self.address, self.port,
                            session_id=self.session_id)
        self.assertFalse(rc)

    @mock.patch.object(socket, 'socket')
    def test_vpn_ping_bad_len(self, mock_socket):
        """Test a short/invalid server reply."""
        self.setup_socket(mock_socket, 'fake_reply')
        rc = utils.vpn_ping(self.address, self.port,
                            session_id=self.session_id)
        self.assertFalse(rc)

    @mock.patch.object(socket, 'socket')
    def test_vpn_ping_bad_id(self, mock_socket):
        """Server sends an unknown packet ID."""
        self.setup_socket(mock_socket, self.fake_reply_packet(pkt_id=0x41))
        rc = utils.vpn_ping(self.address, self.port,
                            session_id=self.session_id)
        self.assertFalse(rc)

    @mock.patch.object(socket, 'socket')
    def test_vpn_ping_ok(self, mock_socket):
        self.setup_socket(mock_socket, self.fake_reply_packet())
        rc = utils.vpn_ping(self.address, self.port,
                            session_id=self.session_id)
        self.assertTrue(rc)


class MonkeyPatchTestCase(test.NoDBTestCase):
    """Unit test for utils.monkey_patch()."""
    def setUp(self):
        super(MonkeyPatchTestCase, self).setUp()
        self.example_package = 'nova.tests.unit.monkey_patch_example.'
        self.flags(
            monkey_patch=True,
            monkey_patch_modules=[self.example_package + 'example_a' + ':'
            + self.example_package + 'example_decorator'])

    def test_monkey_patch(self):
        utils.monkey_patch()
        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION = []
        from nova.tests.unit.monkey_patch_example import example_a
        from nova.tests.unit.monkey_patch_example import example_b

        self.assertEqual('Example function', example_a.example_function_a())
        exampleA = example_a.ExampleClassA()
        exampleA.example_method()
        ret_a = exampleA.example_method_add(3, 5)
        self.assertEqual(ret_a, 8)

        self.assertEqual('Example function', example_b.example_function_b())
        exampleB = example_b.ExampleClassB()
        exampleB.example_method()
        ret_b = exampleB.example_method_add(3, 5)

        self.assertEqual(ret_b, 8)
        package_a = self.example_package + 'example_a.'
        self.assertIn(package_a + 'example_function_a',
                      nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)

        self.assertIn(package_a + 'ExampleClassA.example_method',
                        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertIn(package_a + 'ExampleClassA.example_method_add',
                        nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        package_b = self.example_package + 'example_b.'
        self.assertNotIn(package_b + 'example_function_b',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(package_b + 'ExampleClassB.example_method',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)
        self.assertNotIn(package_b + 'ExampleClassB.example_method_add',
                         nova.tests.unit.monkey_patch_example.CALLED_FUNCTION)


class MonkeyPatchDefaultTestCase(test.NoDBTestCase):
    """Unit test for default monkey_patch_modules value."""

    def setUp(self):
        super(MonkeyPatchDefaultTestCase, self).setUp()
        self.flags(
            monkey_patch=True)

    def test_monkey_patch_default_mod(self):
        # monkey_patch_modules is defined to be
        #    <module_to_patch>:<decorator_to_patch_with>
        #  Here we check that both parts of the default values are
        # valid
        for module in CONF.monkey_patch_modules:
            m = module.split(':', 1)
            # Check we can import the module to be patched
            importlib.import_module(m[0])
            # check the decorator is valid
            decorator_name = m[1].rsplit('.', 1)
            decorator_module = importlib.import_module(decorator_name[0])
            getattr(decorator_module, decorator_name[1])


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


class MkfsTestCase(test.NoDBTestCase):

    @mock.patch('nova.utils.execute')
    def test_mkfs_ext4(self, mock_execute):
        utils.mkfs('ext4', '/my/block/dev')
        mock_execute.assert_called_once_with('mkfs', '-t', 'ext4', '-F',
            '/my/block/dev', run_as_root=False)

    @mock.patch('nova.utils.execute')
    def test_mkfs_msdos(self, mock_execute):
        utils.mkfs('msdos', '/my/msdos/block/dev')
        mock_execute.assert_called_once_with('mkfs', '-t', 'msdos',
            '/my/msdos/block/dev', run_as_root=False)

    @mock.patch('nova.utils.execute')
    def test_mkfs_swap(self, mock_execute):
        utils.mkfs('swap', '/my/swap/block/dev')
        mock_execute.assert_called_once_with('mkswap', '/my/swap/block/dev',
            run_as_root=False)

    @mock.patch('nova.utils.execute')
    def test_mkfs_ext4_withlabel(self, mock_execute):
        utils.mkfs('ext4', '/my/block/dev', 'ext4-vol')
        mock_execute.assert_called_once_with('mkfs', '-t', 'ext4', '-F',
            '-L', 'ext4-vol', '/my/block/dev', run_as_root=False)

    @mock.patch('nova.utils.execute')
    def test_mkfs_msdos_withlabel(self, mock_execute):
        utils.mkfs('msdos', '/my/msdos/block/dev', 'msdos-vol')
        mock_execute.assert_called_once_with('mkfs', '-t', 'msdos',
            '-n', 'msdos-vol', '/my/msdos/block/dev', run_as_root=False)

    @mock.patch('nova.utils.execute')
    def test_mkfs_swap_withlabel(self, mock_execute):
        utils.mkfs('swap', '/my/swap/block/dev', 'swap-vol')
        mock_execute.assert_called_once_with('mkswap', '-L', 'swap-vol',
            '/my/swap/block/dev', run_as_root=False)


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
    def test_valid_inputs(self):
        self.assertEqual(
            utils.validate_integer(42, "answer"), 42)
        self.assertEqual(
            utils.validate_integer("42", "answer"), 42)
        self.assertEqual(
            utils.validate_integer(
                "7", "lucky", min_value=7, max_value=8), 7)
        self.assertEqual(
            utils.validate_integer(
                7, "lucky", min_value=6, max_value=7), 7)
        self.assertEqual(
            utils.validate_integer(
                300, "Spartaaa!!!", min_value=300), 300)
        self.assertEqual(
            utils.validate_integer(
                "300", "Spartaaa!!!", max_value=300), 300)

    def test_invalid_inputs(self):
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


class ResourceFilterTestCase(test.NoDBTestCase):
    def _assert_filtering(self, res_list, filts, expected_tags):
        actual_tags = utils.filter_and_format_resource_metadata('instance',
                res_list, filts, 'metadata')
        self.assertJsonEqual(expected_tags, actual_tags)

    def test_filter_and_format_resource_metadata(self):
        # Create some tags
        # One overlapping pair, and one different key value pair
        # i1 : foo=bar, bax=wibble
        # i2 : foo=bar, baz=quux

        # resources
        i1 = {
                'uuid': '1',
                'metadata': {'foo': 'bar', 'bax': 'wibble'},
            }
        i2 = {
                'uuid': '2',
                'metadata': {'foo': 'bar', 'baz': 'quux'},
            }

        # Resources list
        rl = [i1, i2]

        # tags
        i11 = {'instance_id': '1', 'key': 'foo', 'value': 'bar'}
        i12 = {'instance_id': '1', 'key': 'bax', 'value': 'wibble'}
        i21 = {'instance_id': '2', 'key': 'foo', 'value': 'bar'}
        i22 = {'instance_id': '2', 'key': 'baz', 'value': 'quux'}

        # No filter
        self._assert_filtering(rl, [], [i11, i12, i21, i22])
        self._assert_filtering(rl, {}, [i11, i12, i21, i22])

        # Key search

        # Both should have tags with key 'foo' and value 'bar'
        self._assert_filtering(rl, {'key': 'foo', 'value': 'bar'}, [i11, i21])

        # Both should have tags with key 'foo'
        self._assert_filtering(rl, {'key': 'foo'}, [i11, i21])

        # Only i2 should have tags with key 'baz' and value 'quux'
        self._assert_filtering(rl, {'key': 'baz', 'value': 'quux'}, [i22])

        # Only i2 should have tags with value 'quux'
        self._assert_filtering(rl, {'value': 'quux'}, [i22])

        # Empty list should be returned when no tags match
        self._assert_filtering(rl, {'key': 'split', 'value': 'banana'}, [])

        # Multiple values

        # Only i2 should have tags with key 'baz' and values in the set
        # ['quux', 'wibble']
        self._assert_filtering(rl, {'key': 'baz', 'value': ['quux', 'wibble']},
                [i22])

        # But when specified as two different filters, no tags should be
        # returned. This is because, the filter will mean "return tags which
        # have (key=baz AND value=quux) AND (key=baz AND value=wibble)
        self._assert_filtering(rl, [{'key': 'baz', 'value': 'quux'},
            {'key': 'baz', 'value': 'wibble'}], [])

        # Test for regex
        self._assert_filtering(rl, {'value': '\\Aqu..*\\Z(?s)'}, [i22])

        # Make sure bug #1365887 is fixed
        i1['metadata']['key3'] = 'a'
        self._assert_filtering(rl, {'value': 'banana'}, [])


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
