# Copyright 2016 HPE, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import tempfile

import mock
from oslo_config import cfg

import nova.conf.compute
from nova import config
from nova import test


class ConfTest(test.NoDBTestCase):
    """This is a test and pattern for parsing tricky options."""

    class TestConfigOpts(cfg.ConfigOpts):
        def __call__(self, args=None, default_config_files=None):
            if default_config_files is None:
                default_config_files = []
            return cfg.ConfigOpts.__call__(
                self,
                args=args,
                prog='test',
                version='1.0',
                usage='%(prog)s FOO BAR',
                default_config_files=default_config_files,
                validate_default_values=True)

    def setUp(self):
        super(ConfTest, self).setUp()
        self.conf = self.TestConfigOpts()
        self.tempdirs = []

    def create_tempfiles(self, files, ext='.conf'):
        tempfiles = []
        for (basename, contents) in files:
            if not os.path.isabs(basename):
                (fd, path) = tempfile.mkstemp(prefix=basename, suffix=ext)
            else:
                path = basename + ext
                fd = os.open(path, os.O_CREAT | os.O_WRONLY)
            tempfiles.append(path)
            try:
                os.write(fd, contents.encode('utf-8'))
            finally:
                os.close(fd)
        return tempfiles

    def test_reserved_huge_page(self):
        nova.conf.compute.register_opts(self.conf)

        paths = self.create_tempfiles(
            [('1',
              '[DEFAULT]\n'
              'reserved_huge_pages = node:0,size:2048,count:64\n')])
        self.conf(['--config-file', paths[0]])
        # NOTE(sdague): In oslo.config if you specify a parameter
        # incorrectly, it silently drops it from the conf. Which means
        # the attr doesn't exist at all. The first attr test here is
        # for an unrelated boolean option that is using defaults (so
        # will always work. It's a basic control that *anything* is working.
        self.assertTrue(hasattr(self.conf, 'force_raw_images'))
        self.assertTrue(hasattr(self.conf, 'reserved_huge_pages'),
                        "Parse error with reserved_huge_pages")

        # NOTE(sdague): Yes, this actually parses as an array holding
        # a dict.
        actual = [{'node': '0', 'size': '2048', 'count': '64'}]
        self.assertEqual(actual, self.conf.reserved_huge_pages)


class TestParseArgs(test.NoDBTestCase):

    def setUp(self):
        super(TestParseArgs, self).setUp()
        m = mock.patch('nova.db.sqlalchemy.api.configure')
        self.nova_db_config_mock = m.start()
        self.addCleanup(self.nova_db_config_mock.stop)

    @mock.patch.object(config.log, 'register_options')
    def test_parse_args_glance_debug_false(self, register_options):
        self.flags(debug=False, group='glance')
        config.parse_args([], configure_db=False, init_rpc=False)
        self.assertIn('glanceclient=WARN', config.CONF.default_log_levels)
        self.nova_db_config_mock.assert_not_called()

    @mock.patch.object(config.log, 'register_options')
    def test_parse_args_glance_debug_true(self, register_options):
        self.flags(debug=True, group='glance')
        config.parse_args([], configure_db=True, init_rpc=False)
        self.assertIn('glanceclient=DEBUG', config.CONF.default_log_levels)
        self.nova_db_config_mock.assert_called_once_with(config.CONF)
