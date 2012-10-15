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

from nova import config
from nova import flags
from nova.openstack.common import cfg
from nova import test

CONF = config.CONF
FLAGS = flags.FLAGS
FLAGS.register_opt(cfg.StrOpt('flags_unittest',
                              default='foo',
                              help='for testing purposes only'))


class FlagsTestCase(test.TestCase):
    def test_declare(self):
        self.assert_('answer' not in CONF)
        CONF.import_opt('answer', 'nova.tests.declare_flags')
        self.assert_('answer' in CONF)
        self.assertEqual(CONF.answer, 42)

        # Make sure we don't overwrite anything
        CONF.set_override('answer', 256)
        self.assertEqual(CONF.answer, 256)
        CONF.import_opt('answer', 'nova.tests.declare_flags')
        self.assertEqual(CONF.answer, 256)

    def test_getopt_non_interspersed_args(self):
        self.assert_('runtime_answer' not in FLAGS)

        argv = ['flags_test', 'extra_arg', '--runtime_answer=60']
        args = config.parse_args(argv, default_config_files=[])
        self.assertEqual(len(args), 3)
        self.assertEqual(argv, args)

    def test_runtime_and_unknown_flags(self):
        self.assert_('runtime_answer' not in FLAGS)
        import nova.tests.runtime_flags
        self.assert_('runtime_answer' in FLAGS)
        self.assertEqual(FLAGS.runtime_answer, 54)

    def test_long_vs_short_flags(self):
        FLAGS.clear()
        FLAGS.register_cli_opt(cfg.StrOpt('duplicate_answer_long',
                                          default='val',
                                          help='desc'))
        argv = ['flags_test', '--duplicate_answer=60', 'extra_arg']
        args = config.parse_args(argv, default_config_files=[])

        self.assert_('duplicate_answer' not in FLAGS)
        self.assert_(FLAGS.duplicate_answer_long, 60)

        FLAGS.clear()
        FLAGS.register_cli_opt(cfg.IntOpt('duplicate_answer',
                                          default=60, help='desc'))
        args = config.parse_args(argv, default_config_files=[])
        self.assertEqual(FLAGS.duplicate_answer, 60)
        self.assertEqual(FLAGS.duplicate_answer_long, 'val')

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
        FLAGS.reset()
        self.assertEqual(FLAGS.flags_unittest, 'foo')
