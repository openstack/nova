# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Zadara Storage Inc.
# Copyright (c) 2011 OpenStack LLC.
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
Unit Tests for volume types code
"""
import time

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import test
from nova import utils
from nova.volume import volume_types
from nova.db.sqlalchemy.session import get_session
from nova.db.sqlalchemy import models

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.tests.test_volume_types')


class VolumeTypeTestCase(test.TestCase):
    """Test cases for volume type code"""
    def setUp(self):
        super(VolumeTypeTestCase, self).setUp()

        self.ctxt = context.get_admin_context()
        self.vol_type1_name = str(int(time.time()))
        self.vol_type1_specs = dict(
                    type="physical drive",
                    drive_type="SAS",
                    size="300",
                    rpm="7200",
                    visible="True")
        self.vol_type1 = dict(name=self.vol_type1_name,
                              extra_specs=self.vol_type1_specs)

    def test_volume_type_create_then_destroy(self):
        """Ensure volume types can be created and deleted"""
        prev_all_vtypes = volume_types.get_all_types(self.ctxt)

        volume_types.create(self.ctxt,
                            self.vol_type1_name,
                            self.vol_type1_specs)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        LOG.info(_("Given data: %s"), self.vol_type1_specs)
        LOG.info(_("Result data: %s"), new)

        for k, v in self.vol_type1_specs.iteritems():
            self.assertEqual(v, new['extra_specs'][k],
                             'one of fields doesnt match')

        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(len(prev_all_vtypes) + 1,
                         len(new_all_vtypes),
                         'drive type was not created')

        volume_types.destroy(self.ctxt, self.vol_type1_name)
        new_all_vtypes = volume_types.get_all_types(self.ctxt)
        self.assertEqual(prev_all_vtypes,
                         new_all_vtypes,
                         'drive type was not deleted')

    def test_volume_type_create_then_purge(self):
        """Ensure volume types can be created and deleted"""
        prev_all_vtypes = volume_types.get_all_types(self.ctxt, inactive=1)

        volume_types.create(self.ctxt,
                            self.vol_type1_name,
                            self.vol_type1_specs)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        for k, v in self.vol_type1_specs.iteritems():
            self.assertEqual(v, new['extra_specs'][k],
                             'one of fields doesnt match')

        new_all_vtypes = volume_types.get_all_types(self.ctxt, inactive=1)
        self.assertEqual(len(prev_all_vtypes) + 1,
                         len(new_all_vtypes),
                         'drive type was not created')

        volume_types.destroy(self.ctxt, self.vol_type1_name)
        new_all_vtypes2 = volume_types.get_all_types(self.ctxt, inactive=1)
        self.assertEqual(len(new_all_vtypes),
                         len(new_all_vtypes2),
                         'drive type was incorrectly deleted')

        volume_types.purge(self.ctxt, self.vol_type1_name)
        new_all_vtypes2 = volume_types.get_all_types(self.ctxt, inactive=1)
        self.assertEqual(len(new_all_vtypes) - 1,
                         len(new_all_vtypes2),
                         'drive type was not purged')

    def test_get_all_volume_types(self):
        """Ensures that all volume types can be retrieved"""
        session = get_session()
        total_volume_types = session.query(models.VolumeTypes).\
                                           count()
        vol_types = volume_types.get_all_types(self.ctxt)
        self.assertEqual(total_volume_types, len(vol_types))

    def test_non_existant_inst_type_shouldnt_delete(self):
        """Ensures that volume type creation fails with invalid args"""
        self.assertRaises(exception.ApiError,
                          volume_types.destroy, self.ctxt, "sfsfsdfdfs")

    def test_repeated_vol_types_should_raise_api_error(self):
        """Ensures that volume duplicates raises ApiError"""
        new_name = self.vol_type1_name + "dup"
        volume_types.create(self.ctxt, new_name)
        volume_types.destroy(self.ctxt, new_name)
        self.assertRaises(
                exception.ApiError,
                volume_types.create, self.ctxt, new_name)

    def test_invalid_volume_types_params(self):
        """Ensures that volume type creation fails with invalid args"""
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.destroy, self.ctxt, None)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.purge, self.ctxt, None)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.get_volume_type, self.ctxt, None)
        self.assertRaises(exception.InvalidVolumeType,
                          volume_types.get_volume_type_by_name,
                          self.ctxt, None)

    def test_volume_type_get_by_id_and_name(self):
        """Ensure volume types get returns same entry"""
        volume_types.create(self.ctxt,
                            self.vol_type1_name,
                            self.vol_type1_specs)
        new = volume_types.get_volume_type_by_name(self.ctxt,
                                                   self.vol_type1_name)

        new2 = volume_types.get_volume_type(self.ctxt, new['id'])
        self.assertEqual(new, new2)

    def test_volume_type_search_by_extra_spec(self):
        """Ensure volume types get by extra spec returns correct type"""
        volume_types.create(self.ctxt, "type1", {"key1": "val1",
                                                 "key2": "val2"})
        volume_types.create(self.ctxt, "type2", {"key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type3", {"key3": "another_value",
                                                 "key4": "val4"})

        vol_types = volume_types.get_all_types(self.ctxt,
                        search_opts={'extra_specs': {"key1": "val1"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 1)
        self.assertTrue("type1" in vol_types.keys())
        self.assertEqual(vol_types['type1']['extra_specs'],
                         {"key1": "val1", "key2": "val2"})

        vol_types = volume_types.get_all_types(self.ctxt,
                        search_opts={'extra_specs': {"key2": "val2"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 2)
        self.assertTrue("type1" in vol_types.keys())
        self.assertTrue("type2" in vol_types.keys())

        vol_types = volume_types.get_all_types(self.ctxt,
                        search_opts={'extra_specs': {"key3": "val3"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 1)
        self.assertTrue("type2" in vol_types.keys())

    def test_volume_type_search_by_extra_spec_multiple(self):
        """Ensure volume types get by extra spec returns correct type"""
        volume_types.create(self.ctxt, "type1", {"key1": "val1",
                                                 "key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type2", {"key2": "val2",
                                                 "key3": "val3"})
        volume_types.create(self.ctxt, "type3", {"key1": "val1",
                                                 "key3": "val3",
                                                 "key4": "val4"})

        vol_types = volume_types.get_all_types(self.ctxt,
                        search_opts={'extra_specs': {"key1": "val1",
                                                     "key3": "val3"}})
        LOG.info("vol_types: %s" % vol_types)
        self.assertEqual(len(vol_types), 2)
        self.assertTrue("type1" in vol_types.keys())
        self.assertTrue("type3" in vol_types.keys())
        self.assertEqual(vol_types['type1']['extra_specs'],
                         {"key1": "val1", "key2": "val2", "key3": "val3"})
        self.assertEqual(vol_types['type3']['extra_specs'],
                         {"key1": "val1", "key3": "val3", "key4": "val4"})
