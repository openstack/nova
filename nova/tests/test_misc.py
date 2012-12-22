# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2010 OpenStack LLC
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

import glob
import os

from nova import exception
from nova import test


class ExceptionTestCase(test.TestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc()

    def test_exceptions_raise(self):
        for name in dir(exception):
            exc = getattr(exception, name)
            if isinstance(exc, type):
                self.assertRaises(exc, self._raise_exc, exc)


class ProjectTestCase(test.TestCase):

    def test_all_migrations_have_downgrade(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        py_glob = os.path.join(topdir, "nova", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")
        missing_downgrade = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and not has_downgrade:
                    fname = os.path.basename(path)
                    missing_downgrade.append(fname)

        helpful_msg = (_("The following migrations are missing a downgrade:"
                         "\n\t%s") % '\n\t'.join(sorted(missing_downgrade)))
        self.assert_(not missing_downgrade, helpful_msg)
