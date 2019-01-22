#    Copyright 2013 IBM Corp.
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

import mock
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_versionedobjects import fixture as ovo_fixture

from nova.db import api as db
from nova.objects import instance
from nova.objects import security_group
from nova.tests.unit.objects import test_objects


fake_secgroup = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'name': 'fake-name',
    'description': 'fake-desc',
    'user_id': 'fake-user',
    'project_id': 'fake-project',
    }


class _TestSecurityGroupObject(object):
    def _fix_deleted(self, db_secgroup):
        # NOTE(danms): Account for the difference in 'deleted'
        return dict(db_secgroup.items(), deleted=False)

    @mock.patch.object(db, 'security_group_get',
                       return_value=fake_secgroup)
    def test_get(self, mock_get):
        secgroup = security_group.SecurityGroup.get(self.context, 1)
        ovo_fixture.compare_obj(self, secgroup,
                                self._fix_deleted(fake_secgroup))
        self.assertEqual(secgroup.obj_what_changed(), set())
        mock_get.assert_called_once_with(self.context, 1)

    @mock.patch.object(db, 'security_group_get_by_name',
                       return_value=fake_secgroup)
    def test_get_by_name(self, mock_get):
        secgroup = security_group.SecurityGroup.get_by_name(self.context,
                                                            'fake-project',
                                                            'fake-name')
        ovo_fixture.compare_obj(self, secgroup,
                                self._fix_deleted(fake_secgroup))
        self.assertEqual(secgroup.obj_what_changed(), set())
        mock_get.assert_called_once_with(self.context,
                                         'fake-project',
                                         'fake-name')

    @mock.patch.object(db, 'security_group_in_use',
                       return_value=True)
    def test_in_use(self, mock_inuse):
        secgroup = security_group.SecurityGroup(context=self.context)
        secgroup.id = 123
        self.assertTrue(secgroup.in_use())
        mock_inuse.assert_called_once_with(self.context, 123)

    @mock.patch.object(db, 'security_group_update')
    def test_save(self, mock_update):
        updated_secgroup = dict(fake_secgroup, project_id='changed')
        mock_update.return_value = updated_secgroup
        secgroup = security_group.SecurityGroup._from_db_object(
            self.context, security_group.SecurityGroup(),
            fake_secgroup)
        secgroup.description = 'foobar'
        secgroup.save()
        ovo_fixture.compare_obj(self, secgroup,
                                self._fix_deleted(updated_secgroup))
        self.assertEqual(secgroup.obj_what_changed(), set())
        mock_update.assert_called_once_with(self.context, 1,
                                            {'description': 'foobar'})

    @mock.patch.object(db, 'security_group_update')
    def test_save_no_changes(self, mock_update):
        secgroup = security_group.SecurityGroup._from_db_object(
            self.context, security_group.SecurityGroup(),
            fake_secgroup)
        secgroup.save()
        self.assertFalse(mock_update.called)

    @mock.patch.object(db, 'security_group_get')
    def test_refresh(self, mock_get):
        updated_secgroup = dict(fake_secgroup, description='changed')
        mock_get.return_value = updated_secgroup
        secgroup = security_group.SecurityGroup._from_db_object(
            self.context, security_group.SecurityGroup(self.context),
            fake_secgroup)
        secgroup.refresh()
        ovo_fixture.compare_obj(self, secgroup,
                                self._fix_deleted(updated_secgroup))
        self.assertEqual(secgroup.obj_what_changed(), set())
        mock_get.assert_called_once_with(self.context, 1)

    @mock.patch.object(db, 'security_group_update')
    def test_with_uuid(self, mock_db_update):
        """Tests that we can set a uuid but not save it and it's removed when
        backporting to an older version of the object.
        """
        # Test set/get.
        secgroup = security_group.SecurityGroup(
            self.context, uuid=uuids.neutron_id)
        self.assertEqual(uuids.neutron_id, secgroup.uuid)
        # Test backport.
        primitive = secgroup.obj_to_primitive(target_version='1.2')
        self.assertIn('uuid', primitive['nova_object.data'])
        primitive = secgroup.obj_to_primitive(target_version='1.1')
        self.assertNotIn('uuid', primitive['nova_object.data'])
        # Make sure the uuid is still set before we save().
        self.assertIn('uuid', secgroup)
        secgroup.save()
        self.assertFalse(mock_db_update.called)

    def test_identifier(self):
        secgroup = security_group.SecurityGroup(name='foo')
        self.assertEqual('foo', secgroup.identifier)
        secgroup.uuid = uuids.secgroup
        self.assertEqual(uuids.secgroup, secgroup.identifier)


class TestSecurityGroupObject(test_objects._LocalTest,
                              _TestSecurityGroupObject):
    pass


class TestSecurityGroupObjectRemote(test_objects._RemoteTest,
                                    _TestSecurityGroupObject):
    pass


fake_secgroups = [
    dict(fake_secgroup, id=1, name='secgroup1'),
    dict(fake_secgroup, id=2, name='secgroup2'),
    ]


class _TestSecurityGroupListObject(object):
    @mock.patch.object(db, 'security_group_get_all',
                       return_value=fake_secgroups)
    def test_get_all(self, mock_get):
        secgroup_list = security_group.SecurityGroupList.get_all(self.context)
        for i in range(len(fake_secgroups)):
            self.assertIsInstance(secgroup_list[i],
                                  security_group.SecurityGroup)
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i].id)
            self.assertEqual(secgroup_list[i]._context, self.context)
            mock_get.assert_called_once_with(self.context)

    @mock.patch.object(db, 'security_group_get_by_project',
                       return_value=fake_secgroups)
    def test_get_by_project(self, mock_get):
        secgroup_list = security_group.SecurityGroupList.get_by_project(
            self.context, 'fake-project')
        for i in range(len(fake_secgroups)):
            self.assertIsInstance(secgroup_list[i],
                                  security_group.SecurityGroup)
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i].id)
        mock_get.assert_called_once_with(self.context, 'fake-project')

    @mock.patch.object(db, 'security_group_get_by_instance',
                       return_value=fake_secgroups)
    def test_get_by_instance(self, mock_get):
        inst = instance.Instance()
        inst.uuid = uuids.instance
        secgroup_list = security_group.SecurityGroupList.get_by_instance(
            self.context, inst)
        for i in range(len(fake_secgroups)):
            self.assertIsInstance(secgroup_list[i],
                                  security_group.SecurityGroup)
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i].id)
        mock_get.assert_called_once_with(self.context, inst.uuid)


class TestSecurityGroupListObject(test_objects._LocalTest,
                                  _TestSecurityGroupListObject):
    pass


class TestSecurityGroupListObjectRemote(test_objects._RemoteTest,
                                        _TestSecurityGroupListObject):
    pass
