#    Copyright 2015 Red Hat, Inc.
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

from nova import objects
from nova.objects import migrate_data
from nova.tests.unit.objects import test_objects


class _TestLiveMigrateData(object):
    def test_to_legacy_dict(self):
        obj = migrate_data.LiveMigrateData(is_volume_backed=False)
        self.assertEqual({'is_volume_backed': False},
                         obj.to_legacy_dict())

    def test_from_legacy_dict(self):
        obj = migrate_data.LiveMigrateData()
        obj.from_legacy_dict({'is_volume_backed': False, 'ignore': 'foo'})
        self.assertEqual(False, obj.is_volume_backed)

    def test_from_legacy_dict_migration(self):
        migration = objects.Migration()
        obj = migrate_data.LiveMigrateData()
        obj.from_legacy_dict({'is_volume_backed': False, 'ignore': 'foo',
                              'migration': migration})
        self.assertEqual(False, obj.is_volume_backed)
        self.assertIsInstance(obj.migration, objects.Migration)

    def test_legacy_with_pre_live_migration_result(self):
        obj = migrate_data.LiveMigrateData(is_volume_backed=False)
        self.assertEqual({'pre_live_migration_result': {},
                          'is_volume_backed': False},
                         obj.to_legacy_dict(pre_migration_result=True))


class TestLiveMigrateData(test_objects._LocalTest,
                          _TestLiveMigrateData):
    pass


class TestRemoteLiveMigrateData(test_objects._RemoteTest,
                                _TestLiveMigrateData):
    pass
