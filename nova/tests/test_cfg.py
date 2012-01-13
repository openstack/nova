# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Red Hat, Inc.
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

import os
import sys
import StringIO
import tempfile

import stubout

from nova import test
from nova.common.cfg import *


class BaseTestCase(test.TestCase):

    def setUp(self):
        self.conf = ConfigOpts(prog='test',
                               version='1.0',
                               usage='%prog FOO BAR',
                               default_config_files=[])
        self.tempfiles = []
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.remove_tempfiles()
        self.stubs.UnsetAll()

    def create_tempfiles(self, files):
        for (basename, contents) in files:
            (fd, path) = tempfile.mkstemp(prefix=basename)
            self.tempfiles.append(path)
            try:
                os.write(fd, contents)
            finally:
                os.close(fd)
        return self.tempfiles[-len(files):]

    def remove_tempfiles(self):
        for p in self.tempfiles:
            os.remove(p)


class LeftoversTestCase(BaseTestCase):

    def test_leftovers(self):
        self.conf.register_cli_opt(StrOpt('foo'))
        self.conf.register_cli_opt(StrOpt('bar'))

        leftovers = self.conf(['those', '--foo', 'this',
                               'thems', '--bar', 'that', 'these'])

        self.assertEquals(leftovers, ['those', 'thems', 'these'])


class FindConfigFilesTestCase(BaseTestCase):

    def test_find_config_files(self):
        config_files = \
            [os.path.expanduser('~/.blaa/blaa.conf'), '/etc/foo.conf']

        self.stubs.Set(os.path, 'exists', lambda p: p in config_files)

        self.assertEquals(find_config_files(project='blaa', prog='foo'),
                          config_files)


class CliOptsTestCase(BaseTestCase):

    def _do_cli_test(self, opt_class, default, cli_args, value):
        self.conf.register_cli_opt(opt_class('foo', default=default))

        self.conf(cli_args)

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, value)

    def test_str_default(self):
        self._do_cli_test(StrOpt, None, [], None)

    def test_str_arg(self):
        self._do_cli_test(StrOpt, None, ['--foo', 'bar'], 'bar')

    def test_bool_default(self):
        self._do_cli_test(BoolOpt, False, [], False)

    def test_bool_arg(self):
        self._do_cli_test(BoolOpt, None, ['--foo'], True)

    def test_bool_arg_inverse(self):
        self._do_cli_test(BoolOpt, None, ['--foo', '--nofoo'], False)

    def test_int_default(self):
        self._do_cli_test(IntOpt, 10, [], 10)

    def test_int_arg(self):
        self._do_cli_test(IntOpt, None, ['--foo=20'], 20)

    def test_float_default(self):
        self._do_cli_test(FloatOpt, 1.0, [], 1.0)

    def test_float_arg(self):
        self._do_cli_test(FloatOpt, None, ['--foo', '2.0'], 2.0)

    def test_list_default(self):
        self._do_cli_test(ListOpt, ['bar'], [], ['bar'])

    def test_list_arg(self):
        self._do_cli_test(ListOpt, None,
                          ['--foo', 'blaa,bar'], ['blaa', 'bar'])

    def test_multistr_default(self):
        self._do_cli_test(MultiStrOpt, ['bar'], [], ['bar'])

    def test_multistr_arg(self):
        self._do_cli_test(MultiStrOpt, None,
                          ['--foo', 'blaa', '--foo', 'bar'], ['blaa', 'bar'])

    def test_help(self):
        self.stubs.Set(sys, 'stdout', StringIO.StringIO())
        self.assertRaises(SystemExit, self.conf, ['--help'])
        self.assertTrue('FOO BAR' in sys.stdout.getvalue())
        self.assertTrue('--version' in sys.stdout.getvalue())
        self.assertTrue('--help' in sys.stdout.getvalue())
        self.assertTrue('--config-file=PATH' in sys.stdout.getvalue())

    def test_version(self):
        self.stubs.Set(sys, 'stdout', StringIO.StringIO())
        self.assertRaises(SystemExit, self.conf, ['--version'])
        self.assertTrue('1.0' in sys.stdout.getvalue())

    def test_config_file(self):
        paths = self.create_tempfiles([('1.conf', '[DEFAULT]'),
                                       ('2.conf', '[DEFAULT]')])

        self.conf(['--config-file', paths[0], '--config-file', paths[1]])

        self.assertEquals(self.conf.config_file, paths)


class ConfigFileOptsTestCase(BaseTestCase):

    def test_str_default(self):
        self.conf.register_opt(StrOpt('foo', default='bar'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 'bar')

    def test_str_value(self):
        self.conf.register_opt(StrOpt('foo'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 'bar')

    def test_str_value_override(self):
        self.conf.register_cli_opt(StrOpt('foo'))

        paths = self.create_tempfiles([('1.conf',
                                        '[DEFAULT]\n'
                                        'foo = baar\n'),
                                       ('2.conf',
                                        '[DEFAULT]\n'
                                        'foo = baaar\n')])

        self.conf(['--foo', 'bar',
                   '--config-file', paths[0],
                   '--config-file', paths[1]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 'baaar')

    def test_int_default(self):
        self.conf.register_opt(IntOpt('foo', default=666))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 666)

    def test_int_value(self):
        self.conf.register_opt(IntOpt('foo'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = 666\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 666)

    def test_int_value_override(self):
        self.conf.register_cli_opt(IntOpt('foo'))

        paths = self.create_tempfiles([('1.conf',
                                        '[DEFAULT]\n'
                                        'foo = 66\n'),
                                       ('2.conf',
                                        '[DEFAULT]\n'
                                        'foo = 666\n')])

        self.conf(['--foo', '6',
                   '--config-file', paths[0],
                   '--config-file', paths[1]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 666)

    def test_float_default(self):
        self.conf.register_opt(FloatOpt('foo', default=6.66))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 6.66)

    def test_float_value(self):
        self.conf.register_opt(FloatOpt('foo'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = 6.66\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 6.66)

    def test_float_value_override(self):
        self.conf.register_cli_opt(FloatOpt('foo'))

        paths = self.create_tempfiles([('1.conf',
                                        '[DEFAULT]\n'
                                        'foo = 6.6\n'),
                                       ('2.conf',
                                        '[DEFAULT]\n'
                                        'foo = 6.66\n')])

        self.conf(['--foo', '6',
                   '--config-file', paths[0],
                   '--config-file', paths[1]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, 6.66)

    def test_list_default(self):
        self.conf.register_opt(ListOpt('foo', default=['bar']))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, ['bar'])

    def test_list_value(self):
        self.conf.register_opt(ListOpt('foo'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, ['bar'])

    def test_list_value_override(self):
        self.conf.register_cli_opt(ListOpt('foo'))

        paths = self.create_tempfiles([('1.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar,bar\n'),
                                       ('2.conf',
                                        '[DEFAULT]\n'
                                        'foo = b,a,r\n')])

        self.conf(['--foo', 'bar',
                   '--config-file', paths[0],
                   '--config-file', paths[1]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, ['b', 'a', 'r'])

    def test_multistr_default(self):
        self.conf.register_opt(MultiStrOpt('foo', default=['bar']))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, ['bar'])

    def test_multistr_value(self):
        self.conf.register_opt(MultiStrOpt('foo'))

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, ['bar'])

    def test_multistr_values_append(self):
        self.conf.register_cli_opt(ListOpt('foo'))

        paths = self.create_tempfiles([('1.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar\n'),
                                       ('2.conf',
                                        '[DEFAULT]\n'
                                        'foo = bar\n')])

        self.conf(['--foo', 'bar',
                   '--config-file', paths[0],
                   '--config-file', paths[1]])

        self.assertTrue(hasattr(self.conf, 'foo'))

        # FIXME(markmc): values spread across the CLI and multiple
        #                config files should be appended
        # self.assertEquals(self.conf.foo, ['bar', 'bar', 'bar'])


class OptGroupsTestCase(BaseTestCase):

    def test_arg_group(self):
        blaa_group = OptGroup('blaa')
        self.conf.register_group(blaa_group)
        self.conf.register_cli_opt(StrOpt('foo'), group=blaa_group)

        self.conf(['--blaa-foo', 'bar'])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'bar')

    def test_arg_group_by_name(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_cli_opt(StrOpt('foo'), group='blaa')

        self.conf(['--blaa-foo', 'bar'])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'bar')

    def test_arg_group_with_default(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_cli_opt(StrOpt('foo', default='bar'), group='blaa')

        self.conf([])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'bar')

    def test_arg_group_in_config_file(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_opt(StrOpt('foo'), group='blaa')

        paths = self.create_tempfiles([('test.conf',
                                        '[blaa]\n'
                                        'foo = bar\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'bar')


class TemplateSubstitutionTestCase(BaseTestCase):

    def _prep_test_str_sub(self, foo_default=None, bar_default=None):
        self.conf.register_cli_opt(StrOpt('foo', default=foo_default))
        self.conf.register_cli_opt(StrOpt('bar', default=bar_default))

    def _assert_str_sub(self):
        self.assertTrue(hasattr(self.conf, 'bar'))
        self.assertEquals(self.conf.bar, 'blaa')

    def test_str_sub_default_from_default(self):
        self._prep_test_str_sub(foo_default='blaa', bar_default='$foo')

        self.conf([])

        self._assert_str_sub()

    def test_str_sub_default_from_arg(self):
        self._prep_test_str_sub(bar_default='$foo')

        self.conf(['--foo', 'blaa'])

        self._assert_str_sub()

    def test_str_sub_default_from_config_file(self):
        self._prep_test_str_sub(bar_default='$foo')

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = blaa\n')])

        self.conf(['--config-file', paths[0]])

        self._assert_str_sub()

    def test_str_sub_arg_from_default(self):
        self._prep_test_str_sub(foo_default='blaa')

        self.conf(['--bar', '$foo'])

        self._assert_str_sub()

    def test_str_sub_arg_from_arg(self):
        self._prep_test_str_sub()

        self.conf(['--foo', 'blaa', '--bar', '$foo'])

        self._assert_str_sub()

    def test_str_sub_arg_from_config_file(self):
        self._prep_test_str_sub()

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'foo = blaa\n')])

        self.conf(['--config-file', paths[0], '--bar=$foo'])

        self._assert_str_sub()

    def test_str_sub_config_file_from_default(self):
        self._prep_test_str_sub(foo_default='blaa')

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'bar = $foo\n')])

        self.conf(['--config-file', paths[0]])

        self._assert_str_sub()

    def test_str_sub_config_file_from_arg(self):
        self._prep_test_str_sub()

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'bar = $foo\n')])

        self.conf(['--config-file', paths[0], '--foo=blaa'])

        self._assert_str_sub()

    def test_str_sub_config_file_from_config_file(self):
        self._prep_test_str_sub()

        paths = self.create_tempfiles([('test.conf',
                                        '[DEFAULT]\n'
                                        'bar = $foo\n'
                                        'foo = blaa\n')])

        self.conf(['--config-file', paths[0]])

        self._assert_str_sub()

    def test_str_sub_group_from_default(self):
        self.conf.register_cli_opt(StrOpt('foo', default='blaa'))
        self.conf.register_group(OptGroup('ba'))
        self.conf.register_cli_opt(StrOpt('r', default='$foo'), group='ba')

        self.conf([])

        self.assertTrue(hasattr(self.conf, 'ba'))
        self.assertTrue(hasattr(self.conf.ba, 'r'))
        self.assertEquals(self.conf.ba.r, 'blaa')


class ReparseTestCase(BaseTestCase):

    def test_reparse(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_cli_opt(StrOpt('foo', default='r'), group='blaa')

        paths = self.create_tempfiles([('test.conf',
                                        '[blaa]\n'
                                        'foo = b\n')])

        self.conf(['--config-file', paths[0]])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'b')

        self.conf(['--blaa-foo', 'a'])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'a')

        self.conf([])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertTrue(hasattr(self.conf.blaa, 'foo'))
        self.assertEquals(self.conf.blaa.foo, 'r')


class OverridesTestCase(BaseTestCase):

    def test_no_default_override(self):
        self.conf.register_opt(StrOpt('foo'))
        self.conf([])
        self.assertEquals(self.conf.foo, None)
        self.conf.set_default('foo', 'bar')
        self.assertEquals(self.conf.foo, 'bar')

    def test_default_override(self):
        self.conf.register_opt(StrOpt('foo', default='foo'))
        self.conf([])
        self.assertEquals(self.conf.foo, 'foo')
        self.conf.set_default('foo', 'bar')
        self.assertEquals(self.conf.foo, 'bar')
        self.conf.set_default('foo', None)
        self.assertEquals(self.conf.foo, 'foo')

    def test_override(self):
        self.conf.register_opt(StrOpt('foo'))
        self.conf.set_override('foo', 'bar')
        self.conf([])
        self.assertEquals(self.conf.foo, 'bar')

    def test_group_no_default_override(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_opt(StrOpt('foo'), group='blaa')
        self.conf([])
        self.assertEquals(self.conf.blaa.foo, None)
        self.conf.set_default('foo', 'bar', group='blaa')
        self.assertEquals(self.conf.blaa.foo, 'bar')

    def test_default_override(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_opt(StrOpt('foo', default='foo'), group='blaa')
        self.conf([])
        self.assertEquals(self.conf.blaa.foo, 'foo')
        self.conf.set_default('foo', 'bar', group='blaa')
        self.assertEquals(self.conf.blaa.foo, 'bar')
        self.conf.set_default('foo', None, group='blaa')
        self.assertEquals(self.conf.blaa.foo, 'foo')

    def test_override(self):
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_opt(StrOpt('foo'), group='blaa')
        self.conf.set_override('foo', 'bar', group='blaa')
        self.conf([])
        self.assertEquals(self.conf.blaa.foo, 'bar')


class SadPathTestCase(BaseTestCase):

    def test_unknown_attr(self):
        self.conf([])
        self.assertFalse(hasattr(self.conf, 'foo'))
        self.assertRaises(NoSuchOptError, getattr, self.conf, 'foo')

    def test_unknown_attr_is_attr_error(self):
        self.conf([])
        self.assertFalse(hasattr(self.conf, 'foo'))
        self.assertRaises(AttributeError, getattr, self.conf, 'foo')

    def test_unknown_group_attr(self):
        self.conf.register_group(OptGroup('blaa'))

        self.conf([])

        self.assertTrue(hasattr(self.conf, 'blaa'))
        self.assertFalse(hasattr(self.conf.blaa, 'foo'))
        self.assertRaises(NoSuchOptError, getattr, self.conf.blaa, 'foo')

    def test_ok_duplicate(self):
        opt = StrOpt('foo')
        self.conf.register_cli_opt(opt)
        self.conf.register_cli_opt(opt)

        self.conf([])

        self.assertTrue(hasattr(self.conf, 'foo'))
        self.assertEquals(self.conf.foo, None)

    def test_error_duplicate(self):
        self.conf.register_cli_opt(StrOpt('foo'))
        self.assertRaises(DuplicateOptError,
                          self.conf.register_cli_opt, StrOpt('foo'))

    def test_error_duplicate_with_different_dest(self):
        self.conf.register_cli_opt(StrOpt('foo', dest='f'))
        self.assertRaises(DuplicateOptError,
                          self.conf.register_cli_opt, StrOpt('foo'))

    def test_error_duplicate_short(self):
        self.conf.register_cli_opt(StrOpt('foo', short='f'))
        self.assertRaises(DuplicateOptError,
                          self.conf.register_cli_opt, StrOpt('bar', short='f'))

    def test_no_such_group(self):
        self.assertRaises(NoSuchGroupError, self.conf.register_cli_opt,
                          StrOpt('foo'), group='blaa')

    def test_already_parsed(self):
        self.conf([])

        self.assertRaises(ArgsAlreadyParsedError,
                          self.conf.register_cli_opt, StrOpt('foo'))

    def test_bad_cli_arg(self):
        self.stubs.Set(sys, 'stderr', StringIO.StringIO())

        self.assertRaises(SystemExit, self.conf, ['--foo'])

        self.assertTrue('error' in sys.stderr.getvalue())
        self.assertTrue('--foo' in sys.stderr.getvalue())

    def _do_test_bad_cli_value(self, opt_class):
        self.conf.register_cli_opt(opt_class('foo'))

        self.stubs.Set(sys, 'stderr', StringIO.StringIO())

        self.assertRaises(SystemExit, self.conf, ['--foo', 'bar'])

        self.assertTrue('foo' in sys.stderr.getvalue())
        self.assertTrue('bar' in sys.stderr.getvalue())

    def test_bad_int_arg(self):
        self._do_test_bad_cli_value(IntOpt)

    def test_bad_float_arg(self):
        self._do_test_bad_cli_value(FloatOpt)

    def test_conf_file_not_found(self):
        paths = self.create_tempfiles([('test.conf', '')])
        os.remove(paths[0])
        self.tempfiles.remove(paths[0])

        self.assertRaises(ConfigFilesNotFoundError,
                          self.conf, ['--config-file', paths[0]])

    def test_conf_file_not_found(self):
        paths = self.create_tempfiles([('test.conf', 'foo')])

        self.assertRaises(ConfigFileParseError,
                          self.conf, ['--config-file', paths[0]])

    def _do_test_conf_file_bad_value(self, opt_class):
        self.conf.register_opt(opt_class('foo'))

    def test_conf_file_bad_bool(self):
        self._do_test_conf_file_bad_value(BoolOpt)

    def test_conf_file_bad_int(self):
        self._do_test_conf_file_bad_value(IntOpt)

    def test_conf_file_bad_float(self):
        self._do_test_conf_file_bad_value(FloatOpt)

    def test_str_sub_from_group(self):
        self.conf.register_group(OptGroup('f'))
        self.conf.register_cli_opt(StrOpt('oo', default='blaa'), group='f')
        self.conf.register_cli_opt(StrOpt('bar', default='$f.oo'))

        self.conf([])

        self.assertFalse(hasattr(self.conf, 'bar'))
        self.assertRaises(TemplateSubstitutionError, getattr, self.conf, 'bar')

    def test_set_default_unknown_attr(self):
        self.conf([])
        self.assertRaises(NoSuchOptError, self.conf.set_default, 'foo', 'bar')

    def test_set_default_unknown_group(self):
        self.conf([])
        self.assertRaises(NoSuchGroupError,
                          self.conf.set_default, 'foo', 'bar', group='blaa')

    def test_set_override_unknown_attr(self):
        self.conf([])
        self.assertRaises(NoSuchOptError, self.conf.set_override, 'foo', 'bar')

    def test_set_override_unknown_group(self):
        self.conf([])
        self.assertRaises(NoSuchGroupError,
                          self.conf.set_override, 'foo', 'bar', group='blaa')


class OptDumpingTestCase(BaseTestCase):

    class FakeLogger:

        def __init__(self, test_case, expected_lvl):
            self.test_case = test_case
            self.expected_lvl = expected_lvl
            self.logged = []

        def log(self, lvl, fmt, *args):
            self.test_case.assertEquals(lvl, self.expected_lvl)
            self.logged.append(fmt % args)

    def test_log_opt_values(self):
        self.conf.register_cli_opt(StrOpt('foo'))
        self.conf.register_group(OptGroup('blaa'))
        self.conf.register_cli_opt(StrOpt('bar'), 'blaa')

        self.conf(['--foo', 'this', '--blaa-bar', 'that'])

        logger = self.FakeLogger(self, 666)

        self.conf.log_opt_values(logger, 666)

        self.assertEquals(logger.logged, [
                "*" * 80,
                "Configuration options gathered from:",
                "command line args: ['--foo', 'this', '--blaa-bar', 'that']",
                "config files: []",
                "=" * 80,
                "config_file                    = []",
                "foo                            = this",
                "blaa.bar                       = that",
                "*" * 80,
                ])


class CommonOptsTestCase(BaseTestCase):

    def setUp(self):
        super(CommonOptsTestCase, self).setUp()
        self.conf = CommonConfigOpts()

    def test_debug_verbose(self):
        self.conf(['--debug', '--verbose'])

        self.assertEquals(self.conf.debug, True)
        self.assertEquals(self.conf.verbose, True)

    def test_logging_opts(self):
        self.conf([])

        self.assertTrue(self.conf.log_config is None)
        self.assertTrue(self.conf.log_file is None)
        self.assertTrue(self.conf.log_dir is None)

        self.assertEquals(self.conf.log_format,
                          CommonConfigOpts.DEFAULT_LOG_FORMAT)
        self.assertEquals(self.conf.log_date_format,
                          CommonConfigOpts.DEFAULT_LOG_DATE_FORMAT)

        self.assertEquals(self.conf.use_syslog, False)
