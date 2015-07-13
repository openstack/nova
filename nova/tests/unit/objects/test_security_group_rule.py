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

import mock

from oslo_versionedobjects import exception as ovo_exc

from nova import db
from nova import objects
from nova.tests.unit.objects import test_objects
from nova.tests.unit.objects import test_security_group

fake_rule = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 1,
    'protocol': 'tcp',
    'from_port': 22,
    'to_port': 22,
    'cidr': '0.0.0.0/0',
    }


class _TestSecurityGroupRuleObject(object):
    def test_get_by_id(self):
        with mock.patch.object(db, 'security_group_rule_get') as sgrg:
            sgrg.return_value = fake_rule
            rule = objects.SecurityGroupRule.get_by_id(
                self.context, 1)
            for field in fake_rule:
                if field == 'cidr':
                    self.assertEqual(fake_rule[field], str(getattr(rule,
                                                                   field)))
                else:
                    self.assertEqual(fake_rule[field], getattr(rule, field))
            sgrg.assert_called_with(self.context, 1)

    def test_get_by_security_group(self):
        secgroup = objects.SecurityGroup()
        secgroup.id = 123
        rule = dict(fake_rule)
        rule['grantee_group'] = dict(test_security_group.fake_secgroup, id=123)
        stupid_method = 'security_group_rule_get_by_security_group'
        with mock.patch.object(db, stupid_method) as sgrgbsg:
            sgrgbsg.return_value = [rule]
            rules = (objects.SecurityGroupRuleList.
                     get_by_security_group(self.context, secgroup))
            self.assertEqual(1, len(rules))
            self.assertEqual(123, rules[0].grantee_group.id)

    @mock.patch.object(db, 'security_group_rule_create',
                       return_value=fake_rule)
    def test_create(self, db_mock):
        rule = objects.SecurityGroupRule(context=self.context)
        rule.protocol = 'tcp'
        secgroup = objects.SecurityGroup()
        secgroup.id = 123
        parentgroup = objects.SecurityGroup()
        parentgroup.id = 223
        rule.grantee_group = secgroup
        rule.parent_group = parentgroup
        rule.create()
        updates = db_mock.call_args[0][1]
        self.assertEqual(fake_rule['id'], rule.id)
        self.assertEqual(updates['group_id'], rule.grantee_group.id)
        self.assertEqual(updates['parent_group_id'], rule.parent_group.id)

    @mock.patch.object(db, 'security_group_rule_create',
                       return_value=fake_rule)
    def test_set_id_failure(self, db_mock):
        rule = objects.SecurityGroupRule(context=self.context)
        rule.create()
        self.assertRaises(ovo_exc.ReadOnlyFieldError, setattr,
                          rule, 'id', 124)


class TestSecurityGroupRuleObject(test_objects._LocalTest,
                                  _TestSecurityGroupRuleObject):
    pass


class TestSecurityGroupRuleObjectRemote(test_objects._RemoteTest,
                                        _TestSecurityGroupRuleObject):
    pass


fake_rules = [
    dict(fake_rule, id=1, grantee_group=test_security_group.fake_secgroup),
    dict(fake_rule, id=2, grantee_group=test_security_group.fake_secgroup),
]


class _TestSecurityGroupRuleListObject(object):
    @mock.patch('nova.db.security_group_rule_get_by_instance')
    def test_get_by_instance(self, mock_get):
        mock_get.return_value = fake_rules
        instance = objects.Instance(uuid='fake-uuid')
        rules = objects.SecurityGroupRuleList.get_by_instance(self.context,
                                                              instance)
        mock_get.assert_called_once_with(self.context, instance.uuid)
        self.assertEqual(2, len(rules))
        self.assertEqual([1, 2], [x.id for x in rules])


class TestSecurityGroupRuleListObject(test_objects._LocalTest,
                                      _TestSecurityGroupRuleListObject):
    pass


class TestSecurityGroupRuleListObjectRemote(test_objects._RemoteTest,
                                            _TestSecurityGroupRuleListObject):
    pass
