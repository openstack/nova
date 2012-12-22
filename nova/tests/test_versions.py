# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 Ken Pepple
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

import __builtin__
import StringIO

from nova.openstack.common import cfg
from nova import test
from nova import version


class VersionTestCase(test.TestCase):
    """Test cases for Versions code"""
    def setUp(self):
        """setup test with unchanging values"""
        super(VersionTestCase, self).setUp()
        self.version = version
        self.version.FINAL = False
        self.version.NOVA_VERSION = ['2012', '10']
        self.version.YEAR, self.version.COUNT = self.version.NOVA_VERSION
        self.version.version_info = {'branch_nick': u'LOCALBRANCH',
                                    'revision_id': 'LOCALREVISION',
                                    'revno': 0}
        self.version.NOVA_PACKAGE = "g9ec3421"

    def test_version_string_is_good(self):
        """Ensure version string works"""
        self.assertEqual("2012.10-dev", self.version.version_string())

    def test_canonical_version_string_is_good(self):
        """Ensure canonical version works"""
        self.assertEqual("2012.10", self.version.canonical_version_string())

    def test_final_version_strings_are_identical(self):
        """Ensure final version strings match only at release"""
        self.assertNotEqual(self.version.canonical_version_string(),
                        self.version.version_string())
        self.version.FINAL = True
        self.assertEqual(self.version.canonical_version_string(),
                        self.version.version_string())

    def test_version_string_with_package_is_good(self):
        """Ensure uninstalled code get version string"""
        self.assertEqual("2012.10-g9ec3421",
                        self.version.version_string_with_package())

    def test_release_file(self):
        version.loaded = False
        real_open = __builtin__.open
        real_find_file = cfg.CONF.find_file

        def fake_find_file(self, name):
            if name == "release":
                return "/etc/nova/release"
            return real_find_file(self, name)

        def fake_open(path, *args, **kwargs):
            if path == "/etc/nova/release":
                data = """[Nova]
vendor = ACME Corporation
product = ACME Nova
package = 1337"""
                return StringIO.StringIO(data)

            return real_open(path, *args, **kwargs)

        self.stubs.Set(__builtin__, 'open', fake_open)
        self.stubs.Set(cfg.ConfigOpts, 'find_file', fake_find_file)

        self.assertEqual(version.vendor_string(), "ACME Corporation")
        self.assertEqual(version.product_string(), "ACME Nova")
        self.assertEqual(version.package_string(), "1337")
