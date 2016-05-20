#    Copyright 2013 Red Hat, Inc.
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
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

OPTIONAL_ATTRS = ['parent_group', 'grantee_group']


@base.NovaObjectRegistry.register
class SecurityGroupRule(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added create() and set id as read_only
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'protocol': fields.StringField(nullable=True),
        'from_port': fields.IntegerField(nullable=True),
        'to_port': fields.IntegerField(nullable=True),
        'cidr': fields.IPNetworkField(nullable=True),
        'parent_group': fields.ObjectField('SecurityGroup', nullable=True),
        'grantee_group': fields.ObjectField('SecurityGroup', nullable=True),
        }

    @staticmethod
    def _from_db_subgroup(context, db_group):
        if db_group is None:
            return None
        return objects.SecurityGroup._from_db_object(
            context, objects.SecurityGroup(context), db_group)

    @staticmethod
    def _from_db_object(context, rule, db_rule, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for field in rule.fields:
            if field in expected_attrs:
                setattr(rule, field,
                        rule._from_db_subgroup(context, db_rule[field]))
            elif field not in OPTIONAL_ATTRS:
                setattr(rule, field, db_rule[field])
        rule._context = context
        rule.obj_reset_changes()
        return rule

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                      reason='already created')
        updates = self.obj_get_changes()
        parent_group = updates.pop('parent_group', None)
        if parent_group:
            updates['parent_group_id'] = parent_group.id
        grantee_group = updates.pop('grantee_group', None)
        if grantee_group:
            updates['group_id'] = grantee_group.id
        db_rule = db.security_group_rule_create(self._context, updates)
        self._from_db_object(self._context, self, db_rule)

    @base.remotable_classmethod
    def get_by_id(cls, context, rule_id):
        db_rule = db.security_group_rule_get(context, rule_id)
        return cls._from_db_object(context, cls(), db_rule)


@base.NovaObjectRegistry.register
class SecurityGroupRuleList(base.ObjectListBase, base.NovaObject):
    fields = {
        'objects': fields.ListOfObjectsField('SecurityGroupRule'),
        }
    VERSION = '1.2'

    @base.remotable_classmethod
    def get_by_security_group_id(cls, context, secgroup_id):
        db_rules = db.security_group_rule_get_by_security_group(
            context, secgroup_id, columns_to_join=['grantee_group'])
        return base.obj_make_list(context, cls(context),
                                  objects.SecurityGroupRule, db_rules,
                                  expected_attrs=['grantee_group'])

    @classmethod
    def get_by_security_group(cls, context, security_group):
        return cls.get_by_security_group_id(context, security_group.id)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_rules = db.security_group_rule_get_by_instance(context,
                                                          instance_uuid)
        return base.obj_make_list(context, cls(context),
                                  objects.SecurityGroupRule, db_rules,
                                  expected_attrs=['grantee_group'])

    @classmethod
    def get_by_instance(cls, context, instance):
        return cls.get_by_instance_uuid(context, instance.uuid)
