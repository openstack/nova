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
from nova.objects import base
from nova.objects import fields
from nova.objects import security_group

OPTIONAL_ATTRS = ['parent_group', 'grantee_group']


class SecurityGroupRule(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
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
        return security_group.SecurityGroup._from_db_object(
            context, security_group.SecurityGroup(), db_group)

    @staticmethod
    def _from_db_object(context, rule, db_rule, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for field in rule.fields:
            if field in expected_attrs:
                rule[field] = rule._from_db_subgroup(context, db_rule[field])
            elif field not in OPTIONAL_ATTRS:
                rule[field] = db_rule[field]
        rule._context = context
        rule.obj_reset_changes()
        return rule

    @base.remotable_classmethod
    def get_by_id(cls, context, rule_id):
        db_rule = db.security_group_rule_get(context, rule_id)
        return cls._from_db_object(context, cls(), db_rule)


class SecurityGroupRuleList(base.ObjectListBase, base.NovaObject):
    fields = {
        'objects': fields.ListOfObjectsField('SecurityGroupRule'),
        }
    child_versions = {
        '1.0': '1.0',
        }

    @base.remotable_classmethod
    def get_by_security_group_id(cls, context, secgroup_id):
        db_rules = db.security_group_rule_get_by_security_group(
            context, secgroup_id, columns_to_join=['grantee_group'])
        return base.obj_make_list(context, cls(), SecurityGroupRule, db_rules,
                                  expected_attrs=['grantee_group'])

    @classmethod
    def get_by_security_group(cls, context, security_group):
        return cls.get_by_security_group_id(context, security_group.id)
