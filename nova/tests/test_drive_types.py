# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
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

"""
Unit Tests for drive types codecode
"""
import time

from nova import context
from nova import flags
from nova import log as logging
from nova import test
from nova.vsa import drive_types

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.vsa')


class DriveTypesTestCase(test.TestCase):
    """Test cases for driver types code"""
    def setUp(self):
        super(DriveTypesTestCase, self).setUp()
        self.cntx = context.RequestContext(None, None)
        self.cntx_admin = context.get_admin_context()
        self._dtype = self._create_drive_type()

    def tearDown(self):
        self._dtype = None

    def _create_drive_type(self):
        """Create a volume object."""
        dtype = {}
        dtype['type'] = 'SATA'
        dtype['size_gb'] = 150
        dtype['rpm'] = 5000
        dtype['capabilities'] = None
        dtype['visible'] = True

        LOG.debug(_("Drive Type created %s"), dtype)
        return dtype

    def test_drive_type_create_delete(self):
        dtype = self._dtype
        prev_all_dtypes = drive_types.get_all(self.cntx_admin, False)

        new = drive_types.create(self.cntx_admin, **dtype)
        for k, v in dtype.iteritems():
            self.assertEqual(v, new[k], 'one of fields doesnt match')

        new_all_dtypes = drive_types.get_all(self.cntx_admin, False)
        self.assertNotEqual(len(prev_all_dtypes),
                            len(new_all_dtypes),
                            'drive type was not created')

        drive_types.delete(self.cntx_admin, new['id'])
        new_all_dtypes = drive_types.get_all(self.cntx_admin, False)
        self.assertEqual(prev_all_dtypes,
                         new_all_dtypes,
                         'drive types was not deleted')

    def test_drive_type_check_name_generation(self):
        dtype = self._dtype
        new = drive_types.create(self.cntx_admin, **dtype)
        expected_name = FLAGS.drive_type_template_short % \
                            (dtype['type'], dtype['size_gb'], dtype['rpm'])
        self.assertEqual(new['name'], expected_name,
                        'name was not generated correctly')

        dtype['capabilities'] = 'SEC'
        new2 = drive_types.create(self.cntx_admin, **dtype)
        expected_name = FLAGS.drive_type_template_long % \
                            (dtype['type'], dtype['size_gb'], dtype['rpm'],
                            dtype['capabilities'])
        self.assertEqual(new2['name'], expected_name,
                        'name was not generated correctly')

        drive_types.delete(self.cntx_admin, new['id'])
        drive_types.delete(self.cntx_admin, new2['id'])

    def test_drive_type_create_delete_invisible(self):
        dtype = self._dtype
        dtype['visible'] = False
        prev_all_dtypes = drive_types.get_all(self.cntx_admin, True)
        new = drive_types.create(self.cntx_admin, **dtype)

        new_all_dtypes = drive_types.get_all(self.cntx_admin, True)
        self.assertEqual(prev_all_dtypes, new_all_dtypes)

        new_all_dtypes = drive_types.get_all(self.cntx_admin, False)
        self.assertNotEqual(prev_all_dtypes, new_all_dtypes)

        drive_types.delete(self.cntx_admin, new['id'])

    def test_drive_type_rename_update(self):
        dtype = self._dtype
        dtype['capabilities'] = None

        new = drive_types.create(self.cntx_admin, **dtype)
        for k, v in dtype.iteritems():
            self.assertEqual(v, new[k], 'one of fields doesnt match')

        new_name = 'NEW_DRIVE_NAME'
        new = drive_types.rename(self.cntx_admin, new['name'], new_name)
        self.assertEqual(new['name'], new_name)

        new = drive_types.rename(self.cntx_admin, new_name)
        expected_name = FLAGS.drive_type_template_short % \
                            (dtype['type'], dtype['size_gb'], dtype['rpm'])
        self.assertEqual(new['name'], expected_name)

        changes = {'rpm': 7200}
        new = drive_types.update(self.cntx_admin, new['id'], **changes)
        for k, v in changes.iteritems():
            self.assertEqual(v, new[k], 'one of fields doesnt match')

        drive_types.delete(self.cntx_admin, new['id'])

    def test_drive_type_get(self):
        dtype = self._dtype
        new = drive_types.create(self.cntx_admin, **dtype)

        new2 = drive_types.get(self.cntx_admin, new['id'])
        for k, v in new2.iteritems():
            self.assertEqual(str(new[k]), str(new2[k]),
                             'one of fields doesnt match')

        new2 = drive_types.get_by_name(self.cntx_admin, new['name'])
        for k, v in new.iteritems():
            self.assertEqual(str(new[k]), str(new2[k]),
                             'one of fields doesnt match')

        drive_types.delete(self.cntx_admin, new['id'])
