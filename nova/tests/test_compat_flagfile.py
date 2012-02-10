# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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

import contextlib
import os
import shutil
import StringIO
import stubout
import textwrap
import tempfile
import unittest
import uuid

from nova.compat import flagfile


class ThatLastTwoPercentCoverageTestCase(unittest.TestCase):

    def test_open_file_for_reading(self):
        with flagfile._open_file_for_reading(__file__):
            pass

    def test_open_fd_for_writing(self):
        (fd, path) = tempfile.mkstemp()
        try:
            with flagfile._open_fd_for_writing(fd, None):
                pass
        finally:
            os.remove(path)


class CompatFlagfileTestCase(unittest.TestCase):

    def setUp(self):
        self.stubs = stubout.StubOutForTesting()
        self.files = {}
        self.tempdir = str(uuid.uuid4())
        self.tempfiles = []

        self.stubs.Set(flagfile, '_open_file_for_reading', self._fake_open)
        self.stubs.Set(flagfile, '_open_fd_for_writing', self._fake_open)
        self.stubs.Set(tempfile, 'mkdtemp', self._fake_mkdtemp)
        self.stubs.Set(tempfile, 'mkstemp', self._fake_mkstemp)
        self.stubs.Set(shutil, 'rmtree', self._fake_rmtree)

    def tearDown(self):
        self.stubs.UnsetAll()

    def _fake_open(self, *args):
        @contextlib.contextmanager
        def managed_stringio(path):
            if not path in self.files:
                self.files[path] = ""
            sio = StringIO.StringIO(textwrap.dedent(self.files[path]))
            try:
                yield sio
            finally:
                self.files[path] = sio.getvalue()
                sio.close()
        if len(args) == 2:
            args = args[1:]  # remove the fd arg for fdopen() case
        return managed_stringio(args[0])

    def _fake_mkstemp(self, *args, **kwargs):
        self.assertTrue('dir' in kwargs)
        self.assertEquals(kwargs['dir'], self.tempdir)
        self.tempfiles.append(str(uuid.uuid4()))
        return (None, self.tempfiles[-1])

    def _fake_mkdtemp(self, *args, **kwargs):
        return self.tempdir

    def _fake_rmtree(self, path):
        self.assertEquals(self.tempdir, path)
        self.tempdir = None

    def test_no_args(self):
        before = []
        after = flagfile.handle_flagfiles(before, tempdir=self.tempdir)
        self.assertEquals(after, before)

    def _do_test_empty_flagfile(self, before):
        self.files['foo.flags'] = ''
        after = flagfile.handle_flagfiles(before, tempdir=self.tempdir)
        self.assertEquals(after, ['--config-file=' + self.tempfiles[-1]])
        self.assertEquals(self.files[self.tempfiles[-1]], '[DEFAULT]\n')

    def test_empty_flagfile(self):
        self._do_test_empty_flagfile(['--flagfile=foo.flags'])

    def test_empty_flagfile_separated(self):
        self._do_test_empty_flagfile(['--flagfile', 'foo.flags'])

    def test_empty_flagfile_single_hyphen(self):
        self._do_test_empty_flagfile(['-flagfile=foo.flags'])

    def test_empty_flagfile_single_hyphen_separated_separated(self):
        self._do_test_empty_flagfile(['-flagfile', 'foo.flags'])

    def test_empty_flagfile_with_other_args(self):
        self.files['foo.flags'] = ''

        before = [
            '--foo', 'bar',
            '--flagfile=foo.flags',
            '--blaa=foo',
            '--foo-flagfile',
            '--flagfile-foo'
            ]

        after = flagfile.handle_flagfiles(before, tempdir=self.tempdir)

        self.assertEquals(after, [
                '--foo', 'bar',
                '--config-file=' + self.tempfiles[-1],
                '--blaa=foo',
                '--foo-flagfile',
                '--flagfile-foo'])
        self.assertEquals(self.files[self.tempfiles[-1]], '[DEFAULT]\n')

    def _do_test_flagfile(self, flags, conf):
        self.files['foo.flags'] = flags

        before = ['--flagfile=foo.flags']

        after = flagfile.handle_flagfiles(before, tempdir=self.tempdir)

        self.assertEquals(after,
                          ['--config-file=' + t
                           for t in reversed(self.tempfiles)])
        self.assertEquals(self.files[self.tempfiles[-1]],
                          '[DEFAULT]\n' + conf)

    def test_flagfile(self):
        self._do_test_flagfile('--bar=foo', 'bar=foo\n')

    def test_boolean_flag(self):
        self._do_test_flagfile('--verbose', 'verbose=true\n')

    def test_boolean_inverted_flag(self):
        self._do_test_flagfile('--noverbose', 'verbose=false\n')

    def test_flagfile_comments(self):
        self._do_test_flagfile('--bar=foo\n#foo\n--foo=bar\n//bar',
                               'bar=foo\nfoo=bar\n')

    def test_flagfile_nested(self):
        self.files['bar.flags'] = '--foo=bar'

        self._do_test_flagfile('--flagfile=bar.flags', '')

        self.assertEquals(self.files[self.tempfiles[-2]],
                          '[DEFAULT]\nfoo=bar\n')

    def test_flagfile_managed(self):
        self.files['foo.flags'] = ''
        before = ['--flagfile=foo.flags']
        with flagfile.handle_flagfiles_managed(before) as after:
            self.assertEquals(after, ['--config-file=' + self.tempfiles[-1]])
            self.assertEquals(self.files[self.tempfiles[-1]], '[DEFAULT]\n')
        self.assertTrue(self.tempdir is None)
