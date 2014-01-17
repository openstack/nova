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

from nova import db
from nova.objects import security_group
from nova.objects import security_group_rule
from nova.tests.objects import test_objects
from nova.tests.objects import test_security_group

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
            rule = security_group_rule.SecurityGroupRule.get_by_id(
                self.context, 1)
            for field in fake_rule:
                if field == 'cidr':
                    self.assertEqual(fake_rule[field], str(rule[field]))
                else:
                    self.assertEqual(fake_rule[field], rule[field])
            sgrg.assert_called_with(self.context, 1)

    def test_get_by_security_group(self):
        secgroup = security_group.SecurityGroup()
        secgroup.id = 123
        rule = dict(fake_rule)
        rule['grantee_group'] = dict(test_security_group.fake_secgroup, id=123)
        stupid_method = 'security_group_rule_get_by_security_group'
        with mock.patch.object(db, stupid_method) as sgrgbsg:
            sgrgbsg.return_value = [rule]
            rules = (security_group_rule.SecurityGroupRuleList.
                     get_by_security_group(self.context, secgroup))
            self.assertEqual(1, len(rules))
            self.assertEqual(123, rules[0].grantee_group.id)


class TestSecurityGroupRuleObject(test_objects._LocalTest,
                                  _TestSecurityGroupRuleObject):
    pass


class TestSecurityGroupRuleObjectRemote(test_objects._RemoteTest,
                                        _TestSecurityGroupRuleObject):
    pass
