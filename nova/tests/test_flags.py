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

import os
import tempfile

from nova import flags
from nova.openstack.common import cfg
from nova import test

FLAGS = flags.FLAGS
FLAGS.register_opt(cfg.StrOpt('flags_unittest',
                              default='foo',
                              help='for testing purposes only'))


class FlagsTestCase(test.TestCase):

    def setUp(self):
        super(FlagsTestCase, self).setUp()
        self.FLAGS = flags.NovaConfigOpts()
        self.global_FLAGS = flags.FLAGS

    def test_declare(self):
        self.assert_('answer' not in self.global_FLAGS)
        flags.DECLARE('answer', 'nova.tests.declare_flags')
        self.assert_('answer' in self.global_FLAGS)
        self.assertEqual(self.global_FLAGS.answer, 42)

        # Make sure we don't overwrite anything
        self.global_FLAGS.set_override('answer', 256)
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
        import nova.tests.runtime_flags
        self.assert_('runtime_answer' in self.global_FLAGS)
        self.assertEqual(self.global_FLAGS.runtime_answer, 54)

    def test_long_vs_short_flags(self):
        self.global_FLAGS.reset()
        self.global_FLAGS.register_cli_opt(cfg.StrOpt('duplicate_answer_long',
                                                      default='val',
                                                      help='desc'))
        argv = ['flags_test', '--duplicate_answer=60', 'extra_arg']
        args = self.global_FLAGS(argv)

        self.assert_('duplicate_answer' not in self.global_FLAGS)
        self.assert_(self.global_FLAGS.duplicate_answer_long, 60)

        self.global_FLAGS.reset()
        self.global_FLAGS.register_cli_opt(cfg.IntOpt('duplicate_answer',
                                                      default=60,
                                                      help='desc'))
        args = self.global_FLAGS(argv)
        self.assertEqual(self.global_FLAGS.duplicate_answer, 60)
        self.assertEqual(self.global_FLAGS.duplicate_answer_long, 'val')

    def test_flag_leak_left(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        self.flags(flags_unittest='bar')
        self.assertEqual(FLAGS.flags_unittest, 'bar')

    def test_flag_leak_right(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        self.flags(flags_unittest='bar')
        self.assertEqual(FLAGS.flags_unittest, 'bar')

    def test_flag_overrides(self):
        self.assertEqual(FLAGS.flags_unittest, 'foo')
        self.flags(flags_unittest='bar')
        self.assertEqual(FLAGS.flags_unittest, 'bar')
        self.reset_flags()
        self.assertEqual(FLAGS.flags_unittest, 'foo')

    def test_flagfile(self):
        opts = [
            cfg.StrOpt('string', default='default', help='desc'),
            cfg.IntOpt('int', default=1, help='desc'),
            cfg.BoolOpt('false', default=False, help='desc'),
            cfg.BoolOpt('true', default=True, help='desc'),
            cfg.MultiStrOpt('multi', default=['blaa'], help='desc'),
            ]

        self.FLAGS.register_opts(opts)

        (fd, path) = tempfile.mkstemp(prefix='nova', suffix='.flags')

        try:
            os.write(fd, '--string=foo\n--int=2\n--false\n--notrue\n')
            os.write(fd, '--multi=foo\n')  # FIXME(markmc): --multi=bar\n')
            os.close(fd)

            self.FLAGS(['flags_test', '--flagfile=' + path])

            self.assertEqual(self.FLAGS.string, 'foo')
            self.assertEqual(self.FLAGS.int, 2)
            self.assertEqual(self.FLAGS.false, True)
            self.assertEqual(self.FLAGS.true, False)
            self.assertEqual(self.FLAGS.multi, ['foo'])  # FIXME(markmc): 'bar'

            # Re-parse to test multistring isn't append multiple times
            self.FLAGS(['flags_test', '--flagfile=' + path])
            self.assertEqual(self.FLAGS.multi, ['foo'])  # FIXME(markmc): 'bar'
        finally:
            os.remove(path)

    def test_defaults(self):
        self.FLAGS.register_opt(cfg.StrOpt('foo', default='bar', help='desc'))
        self.assertEqual(self.FLAGS.foo, 'bar')

        self.FLAGS.set_default('foo', 'blaa')
        self.assertEqual(self.FLAGS.foo, 'blaa')

    def test_templated_values(self):
        self.FLAGS.register_opt(cfg.StrOpt('foo', default='foo', help='desc'))
        self.FLAGS.register_opt(cfg.StrOpt('bar', default='bar', help='desc'))
        self.FLAGS.register_opt(cfg.StrOpt('blaa',
                                           default='$foo$bar', help='desc'))
        self.assertEqual(self.FLAGS.blaa, 'foobar')
