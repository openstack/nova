# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

import exceptions
import os
import tempfile

from nova import flags
from nova.openstack.common import cfg
from nova import test

FLAGS = flags.FLAGS
FLAGS.add_option(cfg.StrOpt('flags_unittest',
                            default='foo',
                            help='for testing purposes only'))


class FlagsTestCase(test.TestCase):

    def setUp(self):
        super(FlagsTestCase, self).setUp()
        self.FLAGS = flags.FlagValues()
        self.global_FLAGS = flags.FLAGS

    def test_define(self):
        self.assert_('string' not in self.FLAGS)
        self.assert_('int' not in self.FLAGS)
        self.assert_('false' not in self.FLAGS)
        self.assert_('true' not in self.FLAGS)

        self.FLAGS.add_option(cfg.StrOpt('string',
                                         default='default', help='desc'))
        self.FLAGS.add_option(cfg.IntOpt('int', default=1, help='desc'))
        self.FLAGS.add_option(cfg.BoolOpt('false', default=False, help='desc'))
        self.FLAGS.add_option(cfg.BoolOpt('true', default=True, help='desc'))

        self.assert_(self.FLAGS['string'])
        self.assert_(self.FLAGS['int'])
        self.assert_(self.FLAGS['false'])
        self.assert_(self.FLAGS['true'])
        self.assertEqual(self.FLAGS.string, 'default')
        self.assertEqual(self.FLAGS.int, 1)
        self.assertEqual(self.FLAGS.false, False)
        self.assertEqual(self.FLAGS.true, True)

        argv = ['flags_test',
                '--string', 'foo',
                '--int', '2',
                '--false',
                '--notrue']

        self.FLAGS(argv)
        self.assertEqual(self.FLAGS.string, 'foo')
        self.assertEqual(self.FLAGS.int, 2)
        self.assertEqual(self.FLAGS.false, True)
        self.assertEqual(self.FLAGS.true, False)

    def test_define_float(self):
        self.FLAGS.add_option(cfg.FloatOpt('float', default=6.66, help='desc'))
        self.assertEqual(self.FLAGS.float, 6.66)

    def test_define_multistring(self):
        self.FLAGS.add_option(cfg.MultiStrOpt('multi',
                                              default=['blaa'], help='desc'))

        self.assert_(self.FLAGS['multi'])
        self.assertEqual(self.FLAGS.multi, ['blaa'])

        argv = ['flags_test', '--multi', 'foo', '--multi', 'bar']
        self.FLAGS(argv)

        self.assertEqual(self.FLAGS.multi, ['foo', 'bar'])

        # Re-parse to test multistring isn't append multiple times
        self.FLAGS(argv + ['--unknown1', '--unknown2'])
        self.assertEqual(self.FLAGS.multi, ['foo', 'bar'])

    def test_define_list(self):
        self.FLAGS.add_option(cfg.ListOpt('list',
                                          default=['foo'], help='desc'))

        self.assert_(self.FLAGS['list'])
        self.assertEqual(self.FLAGS.list, ['foo'])

        argv = ['flags_test', '--list=a,b,c,d']
        self.FLAGS(argv)

        self.assertEqual(self.FLAGS.list, ['a', 'b', 'c', 'd'])

    def test_error(self):
        self.FLAGS.add_option(cfg.IntOpt('error', default=1, help='desc'))

        self.assertEqual(self.FLAGS.error, 1)

        argv = ['flags_test', '--error=foo']
        self.assertRaises(exceptions.SystemExit, self.FLAGS, argv)

    def test_declare(self):
        self.assert_('answer' not in self.global_FLAGS)
        flags.DECLARE('answer', 'nova.tests.declare_flags')
        self.assert_('answer' in self.global_FLAGS)
        self.assertEqual(self.global_FLAGS.answer, 42)

        # Make sure we don't overwrite anything
        self.global_FLAGS.answer = 256
        self.assertEqual(self.global_FLAGS.answer, 256)
        flags.DECLARE('answer', 'nova.tests.declare_flags')
        self.assertEqual(self.global_FLAGS.answer, 256)

    def test_getopt_non_interspersed_args(self):
        self.assert_('runtime_answer' not in self.global_FLAGS)

        argv = ['flags_test', 'extra_arg', '--runtime_answer=60']
        args = self.global_FLAGS(argv)
        self.assertEqual(len(args), 3)
        self.assertEqual(argv, args)

    def test_runtime_and_unknown_flags(self):
        self.assert_('runtime_answer' not in self.global_FLAGS)

        argv = ['flags_test', '--runtime_answer=60', 'extra_arg']
        args = self.global_FLAGS(argv)
        self.assertEqual(len(args), 2)
        self.assertEqual(args[1], 'extra_arg')

        self.assert_('runtime_answer' not in self.global_FLAGS)

        import nova.tests.runtime_flags

        self.assert_('runtime_answer' in self.global_FLAGS)
        self.assertEqual(self.global_FLAGS.runtime_answer, 60)

    def test_long_vs_short_flags(self):
        self.global_FLAGS.add_option(cfg.StrOpt('duplicate_answer_long',
                                                default='val', help='desc'))
        argv = ['flags_test', '--duplicate_answer=60', 'extra_arg']
        args = self.global_FLAGS(argv)

        self.assert_('duplicate_answer' not in self.global_FLAGS)
        self.assert_(self.global_FLAGS.duplicate_answer_long, 60)

        self.global_FLAGS.add_option(cfg.IntOpt('duplicate_answer',
                                                default=60, help='desc'))
        self.assertEqual(self.global_FLAGS.duplicate_answer, 60)
        self.assertEqual(self.global_FLAGS.duplicate_answer_long, 'val')

    def test_flag_leak_left(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        FLAGS.flags_unittest = 'bar'
        self.assertEqual(FLAGS.flags_unittest, 'bar')

    def test_flag_leak_right(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        FLAGS.flags_unittest = 'bar'
        self.assertEqual(FLAGS.flags_unittest, 'bar')

    def test_flag_overrides(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        self.flags(flags_unittest='bar')
        self.assertEqual(FLAGS.flags_unittest, 'bar')
        self.assertEqual(FLAGS['flags_unittest'].value, 'bar')
        self.assertEqual(FLAGS.FlagValuesDict()['flags_unittest'], 'bar')
        self.reset_flags()
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        self.assertEqual(FLAGS['flags_unittest'].value, 'foo')
        self.assertEqual(FLAGS.FlagValuesDict()['flags_unittest'], 'foo')

    def test_flagfile(self):
        self.FLAGS.add_option(cfg.StrOpt('string',
                                         default='default', help='desc'))
        self.FLAGS.add_option(cfg.IntOpt('int', default=1, help='desc'))
        self.FLAGS.add_option(cfg.BoolOpt('false', default=False, help='desc'))
        self.FLAGS.add_option(cfg.BoolOpt('true', default=True, help='desc'))
        self.FLAGS.add_option(cfg.MultiStrOpt('multi',
                                              default=['blaa'], help='desc'))

        (fd, path) = tempfile.mkstemp(prefix='nova', suffix='.flags')

        try:
            os.write(fd, '--string=foo\n--int=2\n--false\n--notrue\n')
            os.write(fd, '--multi=foo\n--multi=bar\n')
            os.close(fd)

            self.FLAGS(['flags_test', '--flagfile=' + path])

            self.assertEqual(self.FLAGS.string, 'foo')
            self.assertEqual(self.FLAGS.int, 2)
            self.assertEqual(self.FLAGS.false, True)
            self.assertEqual(self.FLAGS.true, False)
            self.assertEqual(self.FLAGS.multi, ['foo', 'bar'])

            # Re-parse to test multistring isn't append multiple times
            self.FLAGS(['flags_test', '--flagfile=' + path])
            self.assertEqual(self.FLAGS.multi, ['foo', 'bar'])
        finally:
            os.remove(path)

    def test_defaults(self):
        self.FLAGS.add_option(cfg.StrOpt('foo', default='bar', help='desc'))
        self.assertEqual(self.FLAGS.foo, 'bar')

        self.FLAGS['foo'].SetDefault('blaa')
        self.assertEqual(self.FLAGS.foo, 'blaa')

    def test_templated_values(self):
        self.FLAGS.add_option(cfg.StrOpt('foo', default='foo', help='desc'))
        self.FLAGS.add_option(cfg.StrOpt('bar', default='bar', help='desc'))
        self.FLAGS.add_option(cfg.StrOpt('blaa',
                                         default='$foo$bar', help='desc'))
        self.assertEqual(self.FLAGS.blaa, 'foobar')
