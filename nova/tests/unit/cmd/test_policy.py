# Copyright 2016 Cloudbase Solutions Srl
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
    Unit tests for the nova-policy-check CLI interfaces.
"""

import fixtures
import mock
from six.moves import StringIO

from nova.cmd import policy
import nova.conf
from nova import context as nova_context
from nova.db import api as db
from nova import exception
from nova.policies import base as base_policies
from nova.policies import instance_actions as ia_policies
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import policy_fixture

CONF = nova.conf.CONF


class TestPolicyCheck(test.NoDBTestCase):

    def setUp(self):
        super(TestPolicyCheck, self).setUp()
        self.output = StringIO()
        self.useFixture(fixtures.MonkeyPatch('sys.stdout', self.output))
        self.policy = self.useFixture(policy_fixture.RealPolicyFixture())
        self.cmd = policy.PolicyCommands()

    @mock.patch.object(policy.PolicyCommands, '_filter_rules')
    @mock.patch.object(policy.PolicyCommands, '_get_target')
    @mock.patch.object(policy.PolicyCommands, '_get_context')
    def test_check(self, mock_get_context, mock_get_target,
                   mock_filter_rules):
        fake_rules = ['fake:rule', 'faux:roule']
        mock_filter_rules.return_value = fake_rules

        self.cmd.check(target=mock.sentinel.target)

        mock_get_context.assert_called_once_with()
        mock_get_target.assert_called_once_with(mock_get_context.return_value,
                                                mock.sentinel.target)
        mock_filter_rules.assert_called_once_with(
            mock_get_context.return_value, '', mock_get_target.return_value)
        self.assertEqual('\n'.join(fake_rules) + '\n', self.output.getvalue())

    @mock.patch.object(nova_context, 'RequestContext')
    @mock.patch.object(policy, 'CONF')
    def test_get_context(self, mock_CONF, mock_RequestContext):
        context = self.cmd._get_context()

        self.assertEqual(mock_RequestContext.return_value, context)
        mock_RequestContext.assert_called_once_with(
            roles=mock_CONF.os_roles,
            user_id=mock_CONF.os_user_id,
            project_id=mock_CONF.os_tenant_id)

    def test_get_target_none(self):
        target = self.cmd._get_target(mock.sentinel.context, None)
        self.assertIsNone(target)

    def test_get_target_invalid_attribute(self):
        self.assertRaises(exception.InvalidAttribute, self.cmd._get_target,
                          mock.sentinel.context, ['nope=nada'])

    def test_get_target(self):
        expected_target = {
            'project_id': 'fake-proj',
            'user_id': 'fake-user',
            'quota_class': 'fake-quota-class',
            'availability_zone': 'fake-az',
        }
        given_target = ['='.join([key, val])
                        for key, val in expected_target.items()]

        actual_target = self.cmd._get_target(mock.sentinel.context,
                                             given_target)
        self.assertDictEqual(expected_target, actual_target)

    @mock.patch.object(nova_context, 'get_admin_context')
    @mock.patch.object(db, 'instance_get_by_uuid')
    def test_get_target_instance(self, mock_instance_get,
                                 mock_get_admin_context):
        admin_context = nova_context.RequestContext(is_admin=True)
        mock_get_admin_context.return_value = admin_context
        given_target = ['instance_id=fake_id']
        mock_instance_get.return_value = fake_instance.fake_db_instance()
        target = self.cmd._get_target(mock.sentinel.context,
                                      given_target)
        self.assertEqual(target,
            {'user_id': 'fake-user', 'project_id': 'fake-project'})
        mock_instance_get.assert_called_once_with(admin_context,
                                                  'fake_id')

    def _check_filter_rules(self, context=None, target=None,
                            expected_rules=None):
        context = context or nova_context.get_admin_context()
        if expected_rules is None:
            expected_rules = [
                r.name for r in ia_policies.list_rules()]

        passing_rules = self.cmd._filter_rules(
                context, 'os-instance-actions:list', target)
        passing_rules += self.cmd._filter_rules(
                context, 'os-instance-actions:show', target)
        passing_rules += self.cmd._filter_rules(
                context, 'os-instance-actions:events', target)
        passing_rules += self.cmd._filter_rules(
                context, 'os-instance-actions:events:details', target)
        self.assertEqual(set(expected_rules), set(passing_rules))

    def test_filter_rules_non_admin(self):
        context = nova_context.RequestContext()
        rule_conditions = [base_policies.PROJECT_READER_OR_SYSTEM_READER]
        expected_rules = [r.name for r in ia_policies.list_rules() if
                          r.check_str in rule_conditions]
        self._check_filter_rules(context, expected_rules=expected_rules)

    def test_filter_rules_admin(self):
        self._check_filter_rules()

    def test_filter_rules_instance_non_admin(self):
        db_context = nova_context.RequestContext(user_id='fake-user',
                                                 project_id='fake-project')
        instance = fake_instance.fake_instance_obj(db_context)
        context = nova_context.RequestContext()
        expected_rules = [r.name for r in ia_policies.list_rules() if
                          r.check_str == base_policies.RULE_ANY]
        self._check_filter_rules(context, instance, expected_rules)

    def test_filter_rules_instance_admin(self):
        db_context = nova_context.RequestContext(user_id='fake-user',
                                                 project_id='fake-project')
        instance = fake_instance.fake_instance_obj(db_context)
        self._check_filter_rules(target=instance)

    def test_filter_rules_instance_owner(self):
        db_context = nova_context.RequestContext(user_id='fake-user',
                                                 project_id='fake-project')
        instance = fake_instance.fake_instance_obj(db_context)
        rule_conditions = [base_policies.PROJECT_READER_OR_SYSTEM_READER]
        expected_rules = [r.name for r in ia_policies.list_rules() if
                          r.check_str in rule_conditions]
        self._check_filter_rules(db_context, instance, expected_rules)

    @mock.patch.object(policy.config, 'parse_args')
    @mock.patch.object(policy, 'CONF')
    def _check_main(self, mock_CONF, mock_parse_args,
                    category_name='check', expected_return_value=0):
        mock_CONF.category.name = category_name
        return_value = policy.main()

        self.assertEqual(expected_return_value, return_value)
        mock_CONF.register_cli_opts.assert_called_once_with(
            policy.cli_opts)
        mock_CONF.register_cli_opt.assert_called_once_with(
            policy.category_opt)

    @mock.patch.object(policy.version, 'version_string_with_package',
                       return_value="x.x.x")
    def test_main_version(self, mock_version_string):
        self._check_main(category_name='version')
        self.assertEqual("x.x.x\n", self.output.getvalue())

    @mock.patch.object(policy.cmd_common, 'print_bash_completion')
    def test_main_bash_completion(self, mock_print_bash):
        self._check_main(category_name='bash-completion')
        mock_print_bash.assert_called_once_with(policy.CATEGORIES)

    @mock.patch.object(policy.cmd_common, 'get_action_fn')
    def test_main(self, mock_get_action_fn):
        mock_fn = mock.Mock()
        mock_fn_args = [mock.sentinel.arg]
        mock_fn_kwargs = {'key': mock.sentinel.value}
        mock_get_action_fn.return_value = (mock_fn, mock_fn_args,
                                           mock_fn_kwargs)

        self._check_main(expected_return_value=mock_fn.return_value)
        mock_fn.assert_called_once_with(mock.sentinel.arg,
                                        key=mock.sentinel.value)

    @mock.patch.object(policy.cmd_common, 'get_action_fn')
    def test_main_error(self, mock_get_action_fn):
        mock_fn = mock.Mock(side_effect=Exception)
        mock_get_action_fn.return_value = (mock_fn, [], {})

        self._check_main(expected_return_value=1)
        self.assertIn("error: ", self.output.getvalue())
