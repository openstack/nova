# Copyright 2013 Metacloud, Inc
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
from oslo_config import cfg
import webob

from nova.api.openstack.compute.contrib import \
    security_group_default_rules as security_group_default_rules_v2
from nova.api.openstack.compute.plugins.v3 import \
    security_group_default_rules as security_group_default_rules_v21
from nova import context
import nova.db
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes


CONF = cfg.CONF


class AttrDict(dict):
    def __getattr__(self, k):
        return self[k]


def security_group_default_rule_template(**kwargs):
    rule = kwargs.copy()
    rule.setdefault('ip_protocol', 'TCP')
    rule.setdefault('from_port', 22)
    rule.setdefault('to_port', 22)
    rule.setdefault('cidr', '10.10.10.0/24')
    return rule


def security_group_default_rule_db(security_group_default_rule, id=None):
    attrs = security_group_default_rule.copy()
    if id is not None:
        attrs['id'] = id
    return AttrDict(attrs)


class TestSecurityGroupDefaultRulesNeutronV21(test.TestCase):
    controller_cls = (security_group_default_rules_v21.
                      SecurityGroupDefaultRulesController)

    def setUp(self):
        self.flags(security_group_api='neutron')
        super(TestSecurityGroupDefaultRulesNeutronV21, self).setUp()
        self.controller = self.controller_cls()

    def test_create_security_group_default_rule_not_implemented_neutron(self):
        sgr = security_group_default_rule_template()
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotImplemented, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_security_group_default_rules_list_not_implemented_neturon(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotImplemented, self.controller.index,
                          req)

    def test_security_group_default_rules_show_not_implemented_neturon(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotImplemented, self.controller.show,
                          req, '602ed77c-a076-4f9b-a617-f93b847b62c5')

    def test_security_group_default_rules_delete_not_implemented_neturon(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotImplemented, self.controller.delete,
                          req, '602ed77c-a076-4f9b-a617-f93b847b62c5')


class TestSecurityGroupDefaultRulesNeutronV2(test.TestCase):
    controller_cls = (security_group_default_rules_v2.
                      SecurityGroupDefaultRulesController)


class TestSecurityGroupDefaultRulesV21(test.TestCase):
    controller_cls = (security_group_default_rules_v21.
                      SecurityGroupDefaultRulesController)

    def setUp(self):
        super(TestSecurityGroupDefaultRulesV21, self).setUp()
        self.controller = self.controller_cls()

    def test_create_security_group_default_rule(self):
        sgr = security_group_default_rule_template()

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        sgr_dict = dict(security_group_default_rule=sgr)
        res_dict = self.controller.create(req, sgr_dict)
        security_group_default_rule = res_dict['security_group_default_rule']
        self.assertEqual(security_group_default_rule['ip_protocol'],
                         sgr['ip_protocol'])
        self.assertEqual(security_group_default_rule['from_port'],
                         sgr['from_port'])
        self.assertEqual(security_group_default_rule['to_port'],
                         sgr['to_port'])
        self.assertEqual(security_group_default_rule['ip_range']['cidr'],
                         sgr['cidr'])

    def test_create_security_group_default_rule_with_no_to_port(self):
        sgr = security_group_default_rule_template()
        del sgr['to_port']

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_no_from_port(self):
        sgr = security_group_default_rule_template()
        del sgr['from_port']

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_no_ip_protocol(self):
        sgr = security_group_default_rule_template()
        del sgr['ip_protocol']

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_no_cidr(self):
        sgr = security_group_default_rule_template()
        del sgr['cidr']

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        res_dict = self.controller.create(req,
                                          {'security_group_default_rule': sgr})
        security_group_default_rule = res_dict['security_group_default_rule']
        self.assertNotEqual(security_group_default_rule['id'], 0)
        self.assertEqual(security_group_default_rule['ip_range']['cidr'],
                         '0.0.0.0/0')

    def test_create_security_group_default_rule_with_blank_to_port(self):
        sgr = security_group_default_rule_template(to_port='')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_blank_from_port(self):
        sgr = security_group_default_rule_template(from_port='')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_blank_ip_protocol(self):
        sgr = security_group_default_rule_template(ip_protocol='')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_blank_cidr(self):
        sgr = security_group_default_rule_template(cidr='')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        res_dict = self.controller.create(req,
                                          {'security_group_default_rule': sgr})
        security_group_default_rule = res_dict['security_group_default_rule']
        self.assertNotEqual(security_group_default_rule['id'], 0)
        self.assertEqual(security_group_default_rule['ip_range']['cidr'],
                         '0.0.0.0/0')

    def test_create_security_group_default_rule_non_numerical_to_port(self):
        sgr = security_group_default_rule_template(to_port='invalid')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_non_numerical_from_port(self):
        sgr = security_group_default_rule_template(from_port='invalid')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_invalid_ip_protocol(self):
        sgr = security_group_default_rule_template(ip_protocol='invalid')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_invalid_cidr(self):
        sgr = security_group_default_rule_template(cidr='10.10.2222.0/24')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_invalid_to_port(self):
        sgr = security_group_default_rule_template(to_port='666666')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_invalid_from_port(self):
        sgr = security_group_default_rule_template(from_port='666666')

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_create_security_group_default_rule_with_no_body(self):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, None)

    def test_create_duplicate_security_group_default_rule(self):
        sgr = security_group_default_rule_template()

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.controller.create(req, {'security_group_default_rule': sgr})

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          req, {'security_group_default_rule': sgr})

    def test_security_group_default_rules_list(self):
        self.test_create_security_group_default_rule()
        rules = [dict(id=1,
        ip_protocol='TCP',
        from_port=22,
        to_port=22,
        ip_range=dict(cidr='10.10.10.0/24'))]
        expected = {'security_group_default_rules': rules}

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, expected)

    @mock.patch('nova.db.security_group_default_rule_list',
                side_effect=(exception.
                    SecurityGroupDefaultRuleNotFound("Rule Not Found")))
    def test_non_existing_security_group_default_rules_list(self,
                                                            mock_sec_grp_rule):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.index, req)

    def test_default_security_group_default_rule_show(self):
        sgr = security_group_default_rule_template(id=1)

        self.test_create_security_group_default_rule()

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        res_dict = self.controller.show(req, '1')

        security_group_default_rule = res_dict['security_group_default_rule']

        self.assertEqual(security_group_default_rule['ip_protocol'],
                         sgr['ip_protocol'])
        self.assertEqual(security_group_default_rule['to_port'],
                         sgr['to_port'])
        self.assertEqual(security_group_default_rule['from_port'],
                         sgr['from_port'])
        self.assertEqual(security_group_default_rule['ip_range']['cidr'],
                         sgr['cidr'])

    @mock.patch('nova.db.security_group_default_rule_get',
                side_effect=(exception.
                    SecurityGroupDefaultRuleNotFound("Rule Not Found")))
    def test_non_existing_security_group_default_rule_show(self,
                                                           mock_sec_grp_rule):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, '1')

    def test_delete_security_group_default_rule(self):
        sgr = security_group_default_rule_template(id=1)

        self.test_create_security_group_default_rule()

        self.called = False

        def security_group_default_rule_destroy(context, id):
            self.called = True

        def return_security_group_default_rule(context, id):
            self.assertEqual(sgr['id'], id)
            return security_group_default_rule_db(sgr)

        self.stubs.Set(nova.db, 'security_group_default_rule_destroy',
                       security_group_default_rule_destroy)
        self.stubs.Set(nova.db, 'security_group_default_rule_get',
                       return_security_group_default_rule)

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.controller.delete(req, '1')

        self.assertTrue(self.called)

    @mock.patch('nova.db.security_group_default_rule_destroy',
                side_effect=(exception.
                    SecurityGroupDefaultRuleNotFound("Rule Not Found")))
    def test_non_existing_security_group_default_rule_delete(
            self, mock_sec_grp_rule):
        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.delete, req, '1')

    def test_security_group_ensure_default(self):
        sgr = security_group_default_rule_template(id=1)
        self.test_create_security_group_default_rule()

        ctxt = context.get_admin_context()

        setattr(ctxt, 'project_id', 'new_project_id')

        sg = nova.db.security_group_ensure_default(ctxt)
        rules = nova.db.security_group_rule_get_by_security_group(ctxt, sg.id)
        security_group_rule = rules[0]
        self.assertEqual(sgr['id'], security_group_rule.id)
        self.assertEqual(sgr['ip_protocol'], security_group_rule.protocol)
        self.assertEqual(sgr['from_port'], security_group_rule.from_port)
        self.assertEqual(sgr['to_port'], security_group_rule.to_port)
        self.assertEqual(sgr['cidr'], security_group_rule.cidr)


class TestSecurityGroupDefaultRulesV2(test.TestCase):
    controller_cls = (security_group_default_rules_v2.
                      SecurityGroupDefaultRulesController)
