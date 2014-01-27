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

from lxml import etree
from oslo.config import cfg
import webob

from nova.api.openstack.compute.contrib import security_group_default_rules
from nova.api.openstack import wsgi
from nova import context
import nova.db
from nova import test
from nova.tests.api.openstack import fakes


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


class TestSecurityGroupDefaultRules(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupDefaultRules, self).setUp()
        self.controller = \
            security_group_default_rules.SecurityGroupDefaultRulesController()

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
        self.assertRaises(webob.exc.HTTPUnprocessableEntity,
                          self.controller.create, req, None)

    def test_create_duplicate_security_group_default_rule(self):
        sgr = security_group_default_rule_template()

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.controller.create(req, {'security_group_default_rule': sgr})

        req = fakes.HTTPRequest.blank(
            '/v2/fake/os-security-group-default-rules', use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
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


class TestSecurityGroupDefaultRulesXMLDeserializer(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupDefaultRulesXMLDeserializer, self).setUp()
        deserializer = security_group_default_rules.\
            SecurityGroupDefaultRulesXMLDeserializer()
        self.deserializer = deserializer

    def test_create_request(self):
        serial_request = """
<security_group_default_rule>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <ip_protocol>TCP</ip_protocol>
  <cidr>10.10.10.0/24</cidr>
</security_group_default_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_default_rule": {
                "from_port": "22",
                "to_port": "22",
                "ip_protocol": "TCP",
                "cidr": "10.10.10.0/24"
            },
        }
        self.assertEqual(request['body'], expected)

    def test_create_no_to_port_request(self):
        serial_request = """
<security_group_default_rule>
  <from_port>22</from_port>
  <ip_protocol>TCP</ip_protocol>
  <cidr>10.10.10.0/24</cidr>
</security_group_default_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_default_rule": {
            "from_port": "22",
            "ip_protocol": "TCP",
            "cidr": "10.10.10.0/24"
            },
        }
        self.assertEqual(request['body'], expected)

    def test_create_no_from_port_request(self):
        serial_request = """
<security_group_default_rule>
  <to_port>22</to_port>
  <ip_protocol>TCP</ip_protocol>
  <cidr>10.10.10.0/24</cidr>
</security_group_default_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_default_rule": {
                "to_port": "22",
                "ip_protocol": "TCP",
                "cidr": "10.10.10.0/24"
            },
        }
        self.assertEqual(request['body'], expected)

    def test_create_no_ip_protocol_request(self):
        serial_request = """
<security_group_default_rule>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <cidr>10.10.10.0/24</cidr>
</security_group_default_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_default_rule": {
                "from_port": "22",
                "to_port": "22",
                "cidr": "10.10.10.0/24"
            },
        }
        self.assertEqual(request['body'], expected)

    def test_create_no_cidr_request(self):
        serial_request = """
<security_group_default_rule>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <ip_protocol>TCP</ip_protocol>
</security_group_default_rule>"""
        request = self.deserializer.deserialize(serial_request)
        expected = {
            "security_group_default_rule": {
                "from_port": "22",
                "to_port": "22",
                "ip_protocol": "TCP",
            },
        }
        self.assertEqual(request['body'], expected)


class TestSecurityGroupDefaultRuleXMLSerializer(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupDefaultRuleXMLSerializer, self).setUp()
        self.namespace = wsgi.XMLNS_V11
        self.rule_serializer =\
            security_group_default_rules.SecurityGroupDefaultRuleTemplate()
        self.index_serializer =\
            security_group_default_rules.SecurityGroupDefaultRulesTemplate()

    def _tag(self, elem):
        tagname = elem.tag
        self.assertEqual(tagname[0], '{')
        tmp = tagname.partition('}')
        namespace = tmp[0][1:]
        self.assertEqual(namespace, self.namespace)
        return tmp[2]

    def _verify_security_group_default_rule(self, raw_rule, tree):
        self.assertEqual(raw_rule['id'], tree.get('id'))

        seen = set()
        expected = set(['ip_protocol', 'from_port', 'to_port', 'ip_range',
                        'ip_range/cidr'])

        for child in tree:
            child_tag = self._tag(child)
            seen.add(child_tag)
            if child_tag == 'ip_range':
                for gr_child in child:
                    gr_child_tag = self._tag(gr_child)
                    self.assertIn(gr_child_tag, raw_rule[child_tag])
                    seen.add('%s/%s' % (child_tag, gr_child_tag))
                    self.assertEqual(gr_child.text,
                                     raw_rule[child_tag][gr_child_tag])
            else:
                self.assertEqual(child.text, raw_rule[child_tag])
        self.assertEqual(seen, expected)

    def test_rule_serializer(self):
        raw_rule = dict(id='123',
                        ip_protocol='TCP',
                        from_port='22',
                        to_port='22',
                        ip_range=dict(cidr='10.10.10.0/24'))
        rule = dict(security_group_default_rule=raw_rule)
        text = self.rule_serializer.serialize(rule)

        tree = etree.fromstring(text)

        self.assertEqual('security_group_default_rule', self._tag(tree))
        self._verify_security_group_default_rule(raw_rule, tree)

    def test_index_serializer(self):
        rules = [dict(id='123',
                      ip_protocol='TCP',
                      from_port='22',
                      to_port='22',
                      ip_range=dict(cidr='10.10.10.0/24')),
                 dict(id='234',
                      ip_protocol='UDP',
                      from_port='23456',
                      to_port='234567',
                      ip_range=dict(cidr='10.12.0.0/18')),
                 dict(id='345',
                      ip_protocol='tcp',
                      from_port='3456',
                      to_port='4567',
                      ip_range=dict(cidr='192.168.1.0/32'))]

        rules_dict = dict(security_group_default_rules=rules)

        text = self.index_serializer.serialize(rules_dict)

        tree = etree.fromstring(text)
        self.assertEqual('security_group_default_rules', self._tag(tree))
        self.assertEqual(len(rules), len(tree))
        for idx, child in enumerate(tree):
            self._verify_security_group_default_rule(rules[idx], child)
