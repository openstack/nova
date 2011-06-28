# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for `nova.wsgi`."""

import os.path
import tempfile

import unittest

import nova.exception
import nova.test
import nova.wsgi


class TestLoaderNothingExists(unittest.TestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        self._os_path_exists = os.path.exists
        os.path.exists = lambda _: False

    def test_config_not_found(self):
        self.assertRaises(
            nova.exception.PasteConfigNotFound,
            nova.wsgi.Loader,
        )

    def tearDown(self):
        os.path.exists = self._os_path_exists


class TestLoaderNormalFilesystem(unittest.TestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = nova.wsgi.Loader(self.config.name)

    def test_config_found(self):
        self.assertEquals(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            nova.exception.PasteAppNotFound,
            self.loader.load_app,
            "non-existant app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEquals("/tmp", url_parser.directory)

    def tearDown(self):
        self.config.close()


class TestWSGIServer(unittest.TestCase):
    """WSGI server tests."""

    def test_no_app(self):
        server = nova.wsgi.Server("test_app", None)
        self.assertEquals("test_app", server.name)

    def test_start_random_port(self):
        server = nova.wsgi.Server("test_random_port", None, host="127.0.0.1")
        self.assertEqual(0, server.port)
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()
