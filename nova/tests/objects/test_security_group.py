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

from nova import context
from nova import db
from nova.objects import instance
from nova.objects import security_group
from nova.tests.objects import test_objects


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

    def test_get(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_get')
        db.security_group_get(ctxt, 1).AndReturn(fake_secgroup)
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup.get(ctxt, 1)
        self.assertEqual(self._fix_deleted(fake_secgroup),
                         dict(secgroup.items()))
        self.assertEqual(secgroup.obj_what_changed(), set())
        self.assertRemotes()

    def test_get_by_name(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_get_by_name')
        db.security_group_get_by_name(ctxt, 'fake-project',
                                      'fake-name').AndReturn(fake_secgroup)
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup.get_by_name(ctxt,
                                                            'fake-project',
                                                            'fake-name')
        self.assertEqual(self._fix_deleted(fake_secgroup),
                         dict(secgroup.items()))
        self.assertEqual(secgroup.obj_what_changed(), set())
        self.assertRemotes()

    def test_in_use(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_in_use')
        db.security_group_in_use(ctxt, 123).AndReturn(True)
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup()
        secgroup.id = 123
        self.assertTrue(secgroup.in_use(ctxt))
        self.assertRemotes()

    def test_save(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_update')
        updated_secgroup = dict(fake_secgroup, project_id='changed')
        db.security_group_update(ctxt, 1,
                                 {'description': 'foobar'}).AndReturn(
                                     updated_secgroup)
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup._from_db_object(
            security_group.SecurityGroup(), fake_secgroup)
        secgroup.description = 'foobar'
        secgroup.save(ctxt)
        self.assertEqual(self._fix_deleted(updated_secgroup),
                         dict(secgroup.items()))
        self.assertEqual(secgroup.obj_what_changed(), set())
        self.assertRemotes()

    def test_save_no_changes(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_update')
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup._from_db_object(
            security_group.SecurityGroup(), fake_secgroup)
        secgroup.save(ctxt)

    def test_refresh(self):
        ctxt = context.get_admin_context()
        updated_secgroup = dict(fake_secgroup, description='changed')
        self.mox.StubOutWithMock(db, 'security_group_get')
        db.security_group_get(ctxt, 1).AndReturn(updated_secgroup)
        self.mox.ReplayAll()
        secgroup = security_group.SecurityGroup._from_db_object(
            security_group.SecurityGroup(), fake_secgroup)
        secgroup.refresh(ctxt)
        self.assertEqual(self._fix_deleted(updated_secgroup),
                         dict(secgroup.items()))
        self.assertEqual(secgroup.obj_what_changed(), set())
        self.assertRemotes()


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
    def test_get_all(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_get_all')
        db.security_group_get_all(ctxt).AndReturn(fake_secgroups)
        self.mox.ReplayAll()
        secgroup_list = security_group.SecurityGroupList.get_all(ctxt)
        for i in range(len(fake_secgroups)):
            self.assertTrue(isinstance(secgroup_list[i],
                                       security_group.SecurityGroup))
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i]['id'])
            self.assertEqual(secgroup_list[i]._context, ctxt)

    def test_get_by_project(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'security_group_get_by_project')
        db.security_group_get_by_project(ctxt,
                                         'fake-project').AndReturn(
                                             fake_secgroups)
        self.mox.ReplayAll()
        secgroup_list = security_group.SecurityGroupList.get_by_project(
            ctxt, 'fake-project')
        for i in range(len(fake_secgroups)):
            self.assertTrue(isinstance(secgroup_list[i],
                                       security_group.SecurityGroup))
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i]['id'])

    def test_get_by_instance(self):
        ctxt = context.get_admin_context()

        inst = instance.Instance()
        inst.uuid = 'fake-inst-uuid'
        self.mox.StubOutWithMock(db, 'security_group_get_by_instance')
        db.security_group_get_by_instance(ctxt,
                                          'fake-inst-uuid').AndReturn(
                                              fake_secgroups)
        self.mox.ReplayAll()
        secgroup_list = security_group.SecurityGroupList.get_by_instance(
            ctxt, inst)
        for i in range(len(fake_secgroups)):
            self.assertTrue(isinstance(secgroup_list[i],
                                       security_group.SecurityGroup))
            self.assertEqual(fake_secgroups[i]['id'],
                             secgroup_list[i]['id'])


class TestSecurityGroupListObject(test_objects._LocalTest,
                                  _TestSecurityGroupListObject):
    pass


class TestSecurityGroupListObjectRemote(test_objects._RemoteTest,
                                        _TestSecurityGroupListObject):
    pass
