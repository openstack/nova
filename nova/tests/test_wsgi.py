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

import unittest2 as unittest

import nova.exception
import nova.test
import nova.wsgi


class TestNothingExists(unittest.TestCase):
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


class TestNormalFilesystem(unittest.TestCase):
    """Loader tests where os.path.exists always returns True."""

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
