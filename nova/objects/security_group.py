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

from nova import db
from nova.objects import base


class SecurityGroup(base.NovaObject):
    fields = {
        'id': int,
        'name': str,
        'description': str,
        'user_id': str,
        'project_id': str,
        }

    @staticmethod
    def _from_db_object(secgroup, db_secgroup):
        # NOTE(danms): These are identical right now
        for field in secgroup.fields:
            secgroup[field] = db_secgroup[field]
        secgroup.obj_reset_changes()
        return secgroup

    @base.remotable_classmethod
    def get(cls, context, secgroup_id):
        db_secgroup = db.security_group_get(context, secgroup_id)
        return cls._from_db_object(cls(), db_secgroup)

    @base.remotable_classmethod
    def get_by_name(cls, context, project_id, group_name):
        db_secgroup = db.security_group_get_by_name(context,
                                                    project_id,
                                                    group_name)
        return cls._from_db_object(cls(), db_secgroup)

    @base.remotable
    def in_use(self, context):
        return db.security_group_in_use(context, self.id)

    @base.remotable
    def save(self, context):
        updates = {}
        for field in self.obj_what_changed():
            updates[field] = self[field]
        if updates:
            db_secgroup = db.security_group_update(context, self.id, updates)
            SecurityGroup._from_db_object(self, db_secgroup)
        self.obj_reset_changes()

    @base.remotable
    def refresh(self, context):
        SecurityGroup._from_db_object(self,
                                      db.security_group_get(context,
                                                            self.id))


def _make_secgroup_list(context, secgroup_list, db_secgroup_list):
    secgroup_list.objects = []
    for db_secgroup in db_secgroup_list:
        secgroup = SecurityGroup._from_db_object(SecurityGroup(), db_secgroup)
        secgroup._context = context
        secgroup_list.objects.append(secgroup)
    secgroup_list.obj_reset_changes()
    return secgroup_list


class SecurityGroupList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_all(cls, context):
        return _make_secgroup_list(context, cls(),
                                   db.security_group_get_all(context))

    @base.remotable_classmethod
    def get_by_project(cls, context, project_id):
        return _make_secgroup_list(context, cls(),
                                   db.security_group_get_by_project(
                                       context, project_id))

    @base.remotable_classmethod
    def get_by_instance(cls, context, instance):
        return _make_secgroup_list(context, cls(),
                                   db.security_group_get_by_instance(
                                       context, instance.uuid))


def make_secgroup_list(security_groups):
    """A helper to make security group objects from a list of names.

    Note that this does not make them save-able or have the rest of the
    attributes they would normally have, but provides a quick way to fill,
    for example, an instance object during create.
    """
    secgroups = SecurityGroupList()
    secgroups.objects = []
    for name in security_groups:
        secgroup = SecurityGroup()
        secgroup.name = name
        secgroups.objects.append(secgroup)
    return secgroups
