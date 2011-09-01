# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC
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

import json
import mox
import nova
import unittest
import webob
from xml.dom import minidom

from nova import exception
from nova import test
from nova.api.openstack.contrib import security_groups
from nova.tests.api.openstack import fakes


def _get_create_request_json(body_dict):
    req = webob.Request.blank('/v1.1/123/os-security-groups')
    req.headers['Content-Type'] = 'application/json'
    req.method = 'POST'
    req.body = json.dumps(body_dict)
    return req


def _create_security_group_json(security_group):
    body_dict = _create_security_group_request_dict(security_group)
    request = _get_create_request_json(body_dict)
    response = request.get_response(fakes.wsgi_app())
    return response


def _create_security_group_request_dict(security_group):
    sg = {}
    if security_group is not None:
        name = security_group.get('name', None)
        description = security_group.get('description', None)
        if name:
            sg['name'] = security_group['name']
        if description:
            sg['description'] = security_group['description']
    return {'security_group': sg}


def return_server(context, server_id):
    return {'id': server_id, 'state': 0x01, 'host': "localhost"}


def return_non_running_server(context, server_id):
    return {'id': server_id, 'state': 0x02,
                        'host': "localhost"}


def return_security_group(context, project_id, group_name):
    return {'id': 1, 'name': group_name, "instances": [
              {'id': 1}]}


def return_security_group_without_instances(context, project_id, group_name):
    return {'id': 1, 'name': group_name}


def return_server_nonexistant(context, server_id):
    raise exception.InstanceNotFound(instance_id=server_id)


class TestSecurityGroups(test.TestCase):
    def setUp(self):
        super(TestSecurityGroups, self).setUp()

    def tearDown(self):
        super(TestSecurityGroups, self).tearDown()

    def _create_security_group_request_dict(self, security_group):
        sg = {}
        if security_group is not None:
            name = security_group.get('name', None)
            description = security_group.get('description', None)
            if name:
                sg['name'] = security_group['name']
            if description:
                sg['description'] = security_group['description']
        return {'security_group': sg}

    def _format_create_xml_request_body(self, body_dict):
        sg = body_dict['security_group']
        body_parts = []
        body_parts.extend([
                  '<?xml version="1.0" encoding="UTF-8"?>',
                  '<security_group xmlns="http://docs.openstack.org/ext/'
                  'securitygroups/api/v1.1"',
                  ' name="%s">' % (sg['name'])])
        if 'description' in sg:
            body_parts.append('<description>%s</description>'
                              % sg['description'])
        body_parts.append('</security_group>')
        return ''.join(body_parts)

    def _get_create_request_xml(self, body_dict):
        req = webob.Request.blank('/v1.1/123/os-security-groups')
        req.headers['Content-Type'] = 'application/xml'
        req.content_type = 'application/xml'
        req.accept = 'application/xml'
        req.method = 'POST'
        req.body = self._format_create_xml_request_body(body_dict)
        return req

    def _create_security_group_xml(self, security_group):
        body_dict = self._create_security_group_request_dict(security_group)
        request = self._get_create_request_xml(body_dict)
        response = request.get_response(fakes.wsgi_app())
        return response

    def _delete_security_group(self, id):
        request = webob.Request.blank('/v1.1/123/os-security-groups/%s'
                                      % id)
        request.method = 'DELETE'
        response = request.get_response(fakes.wsgi_app())
        return response

    def test_create_security_group_json(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        res_dict = json.loads(response.body)
        self.assertEqual(res_dict['security_group']['name'], "test")
        self.assertEqual(res_dict['security_group']['description'],
                         "group-description")
        self.assertEquals(response.status_int, 200)

    def test_create_security_group_xml(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = \
                self._create_security_group_xml(security_group)

        self.assertEquals(response.status_int, 200)
        dom = minidom.parseString(response.body)
        sg = dom.childNodes[0]
        self.assertEquals(sg.nodeName, 'security_group')
        self.assertEqual(security_group['name'], sg.getAttribute('name'))

    def test_create_security_group_with_no_name_json(self):
        security_group = {}
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_no_description_json(self):
        security_group = {}
        security_group['name'] = "test"
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_blank_name_json(self):
        security_group = {}
        security_group['name'] = ""
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_whitespace_name_json(self):
        security_group = {}
        security_group['name'] = " "
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_blank_description_json(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = ""
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_whitespace_description_json(self):
        security_group = {}
        security_group['name'] = "name"
        security_group['description'] = " "
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_duplicate_name_json(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)

        self.assertEquals(response.status_int, 200)
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_with_no_body_json(self):
        request = _get_create_request_json(body_dict=None)
        response = request.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 422)

    def test_create_security_group_with_no_security_group(self):
        body_dict = {}
        body_dict['no-securityGroup'] = None
        request = _get_create_request_json(body_dict)
        response = request.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 422)

    def test_create_security_group_above_255_characters_name_json(self):
        security_group = {}
        security_group['name'] = ("1234567890123456"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890")
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)

        self.assertEquals(response.status_int, 400)

    def test_create_security_group_above_255_characters_description_json(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = ("1234567890123456"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890"
                            "1234567890123456789012345678901234567890")
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_non_string_name_json(self):
        security_group = {}
        security_group['name'] = 12
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_create_security_group_non_string_description_json(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = 12
        response = _create_security_group_json(security_group)
        self.assertEquals(response.status_int, 400)

    def test_get_security_group_list(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)

        req = webob.Request.blank('/v1.1/123/os-security-groups')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'GET'
        response = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(response.body)

        expected = {'security_groups': [
                    {'id': 1,
                            'name':"default",
                            'tenant_id': "123",
                            "description":"default",
                            "rules": []
                       },
                     ]
        }
        expected['security_groups'].append(
                    {
                        'id': 2,
                        'name': "test",
                        'tenant_id': "123",
                        "description": "group-description",
                        "rules": []
                    }
                )
        self.assertEquals(response.status_int, 200)
        self.assertEquals(res_dict, expected)

    def test_get_security_group_by_id(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)

        res_dict = json.loads(response.body)
        req = webob.Request.blank('/v1.1/123/os-security-groups/%s' %
                                  res_dict['security_group']['id'])
        req.headers['Content-Type'] = 'application/json'
        req.method = 'GET'
        response = req.get_response(fakes.wsgi_app())
        res_dict = json.loads(response.body)

        expected = {
                      'security_group': {
                          'id': 2,
                          'name': "test",
                          'tenant_id': "123",
                          'description': "group-description",
                          'rules': []
                       }
                   }
        self.assertEquals(res_dict, expected)

    def test_get_security_group_by_invalid_id(self):
        req = webob.Request.blank('/v1.1/123/os-security-groups/invalid')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'GET'
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_get_security_group_by_non_existing_id(self):
        req = webob.Request.blank('/v1.1/123/os-security-groups/111111111')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'GET'
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 404)

    def test_delete_security_group_by_id(self):
        security_group = {}
        security_group['name'] = "test"
        security_group['description'] = "group-description"
        response = _create_security_group_json(security_group)
        security_group = json.loads(response.body)['security_group']
        response = self._delete_security_group(security_group['id'])
        self.assertEquals(response.status_int, 202)

        response = self._delete_security_group(security_group['id'])
        self.assertEquals(response.status_int, 404)

    def test_delete_security_group_by_invalid_id(self):
        response = self._delete_security_group('invalid')
        self.assertEquals(response.status_int, 400)

    def test_delete_security_group_by_non_existing_id(self):
        response = self._delete_security_group(11111111)
        self.assertEquals(response.status_int, 404)

    def test_associate_by_non_existing_security_group_name(self):
        body = dict(addSecurityGroup=dict(name='non-existing'))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 404)

    def test_associate_by_invalid_server_id(self):
        body = dict(addSecurityGroup=dict(name='test'))
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        req = webob.Request.blank('/v1.1/123/servers/invalid/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate_without_body(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(addSecurityGroup=None)
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate_no_security_group_name(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(addSecurityGroup=dict())
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate_security_group_name_with_whitespaces(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(addSecurityGroup=dict(name="   "))
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate_non_existing_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        body = dict(addSecurityGroup=dict(name="test"))
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        req = webob.Request.blank('/v1.1/123/servers/10000/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 404)

    def test_associate_non_running_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_non_running_server)
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(addSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate_already_associated_security_group_to_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        body = dict(addSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_associate(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.mox.StubOutWithMock(nova.db.api, 'instance_add_security_group')
        nova.db.api.instance_add_security_group(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg())
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group_without_instances)
        self.mox.ReplayAll()

        body = dict(addSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 202)

    def test_associate_xml(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.mox.StubOutWithMock(nova.db.api, 'instance_add_security_group')
        nova.db.api.instance_add_security_group(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg())
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group_without_instances)
        self.mox.ReplayAll()

        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/xml'
        req.method = 'POST'
        req.body = """<addSecurityGroup>
                           <name>test</name>
                    </addSecurityGroup>"""
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 202)

    def test_disassociate_by_non_existing_security_group_name(self):
        body = dict(removeSecurityGroup=dict(name='non-existing'))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 404)

    def test_disassociate_by_invalid_server_id(self):
        body = dict(removeSecurityGroup=dict(name='test'))
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        req = webob.Request.blank('/v1.1/123/servers/invalid/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate_without_body(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(removeSecurityGroup=None)
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate_no_security_group_name(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(removeSecurityGroup=dict())
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate_security_group_name_with_whitespaces(self):
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        body = dict(removeSecurityGroup=dict(name="   "))
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate_non_existing_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server_nonexistant)
        body = dict(removeSecurityGroup=dict(name="test"))
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        req = webob.Request.blank('/v1.1/123/servers/10000/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 404)

    def test_disassociate_non_running_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_non_running_server)
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        body = dict(removeSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate_already_associated_security_group_to_instance(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group_without_instances)
        body = dict(removeSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 400)

    def test_disassociate(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.mox.StubOutWithMock(nova.db.api, 'instance_remove_security_group')
        nova.db.api.instance_remove_security_group(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg())
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        self.mox.ReplayAll()

        body = dict(removeSecurityGroup=dict(name="test"))
        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = json.dumps(body)
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 202)

    def test_disassociate_xml(self):
        self.stubs.Set(nova.db.api, 'instance_get', return_server)
        self.mox.StubOutWithMock(nova.db.api, 'instance_remove_security_group')
        nova.db.api.instance_remove_security_group(mox.IgnoreArg(),
                                    mox.IgnoreArg(),
                                    mox.IgnoreArg())
        self.stubs.Set(nova.db.api, 'security_group_get_by_name',
                       return_security_group)
        self.mox.ReplayAll()

        req = webob.Request.blank('/v1.1/123/servers/1/action')
        req.headers['Content-Type'] = 'application/xml'
        req.method = 'POST'
        req.body = """<removeSecurityGroup>
                           <name>test</name>
                    </removeSecurityGroup>"""
        response = req.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 202)


class TestSecurityGroupRules(test.TestCase):
    def setUp(self):
        super(TestSecurityGroupRules, self).setUp()
        security_group = {}
        security_group['name'] = "authorize-revoke"
        security_group['description'] = ("Security group created for "
                                        " authorize-revoke testing")
        response = _create_security_group_json(security_group)
        security_group = json.loads(response.body)
        self.parent_security_group = security_group['security_group']

        rules = {
                  "security_group_rule": {
                        "ip_protocol": "tcp",
                        "from_port": "22",
                        "to_port": "22",
                        "parent_group_id": self.parent_security_group['id'],
                        "cidr": "10.0.0.0/24"
                    }
                }
        res = self._create_security_group_rule_json(rules)
        self.assertEquals(res.status_int, 200)
        self.security_group_rule = json.loads(res.body)['security_group_rule']

    def tearDown(self):
        super(TestSecurityGroupRules, self).tearDown()

    def _create_security_group_rule_json(self, rules):
        request = webob.Request.blank('/v1.1/123/os-security-group-rules')
        request.headers['Content-Type'] = 'application/json'
        request.method = 'POST'
        request.body = json.dumps(rules)
        response = request.get_response(fakes.wsgi_app())
        return response

    def _delete_security_group_rule(self, id):
        request = webob.Request.blank('/v1.1/123/os-security-group-rules/%s'
                                      % id)
        request.method = 'DELETE'
        response = request.get_response(fakes.wsgi_app())
        return response

    def test_create_by_cidr_json(self):
        rules = {
                  "security_group_rule": {
                        "ip_protocol": "tcp",
                        "from_port": "22",
                        "to_port": "22",
                        "parent_group_id": 2,
                        "cidr": "10.2.3.124/24"
                     }
                  }

        response = self._create_security_group_rule_json(rules)
        security_group_rule = json.loads(response.body)['security_group_rule']
        self.assertEquals(response.status_int, 200)
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'], 2)
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "10.2.3.124/24")

    def test_create_by_group_id_json(self):
        rules = {
                  "security_group_rule": {
                        "ip_protocol": "tcp",
                        "from_port": "22",
                        "to_port": "22",
                        "group_id": "1",
                        "parent_group_id": "%s"
                                       % self.parent_security_group['id'],
                     }
                  }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 200)
        security_group_rule = json.loads(response.body)['security_group_rule']
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'], 2)

    def test_create_add_existing_rules_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "cidr": "10.0.0.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_no_body_json(self):
        request = webob.Request.blank('/v1.1/123/os-security-group-rules')
        request.headers['Content-Type'] = 'application/json'
        request.method = 'POST'
        request.body = json.dumps(None)
        response = request.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 422)

    def test_create_with_no_security_group_rule_in_body_json(self):
        request = webob.Request.blank('/v1.1/123/os-security-group-rules')
        request.headers['Content-Type'] = 'application/json'
        request.method = 'POST'
        body_dict = {'test': "test"}
        request.body = json.dumps(body_dict)
        response = request.get_response(fakes.wsgi_app())
        self.assertEquals(response.status_int, 422)

    def test_create_with_invalid_parent_group_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "parent_group_id": "invalid"
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_non_existing_parent_group_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "group_id": "invalid",
                  "parent_group_id": "1111111111111"
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 404)

    def test_create_with_invalid_protocol_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "invalid-protocol",
                  "from_port": "22",
                  "to_port": "22",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_no_protocol_json(self):
        rules = {
              "security_group_rule": {
                  "from_port": "22",
                  "to_port": "22",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_invalid_from_port_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "666666",
                  "to_port": "22",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_invalid_to_port_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "666666",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_non_numerical_from_port_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "invalid",
                  "to_port": "22",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_non_numerical_to_port_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "invalid",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_no_to_port_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "cidr": "10.2.2.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_invalid_cidr_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "cidr": "10.2.22222.0/24",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_no_cidr_group_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        security_group_rule = json.loads(response.body)['security_group_rule']
        self.assertEquals(response.status_int, 200)
        self.assertNotEquals(security_group_rule['id'], 0)
        self.assertEquals(security_group_rule['parent_group_id'],
                          self.parent_security_group['id'])
        self.assertEquals(security_group_rule['ip_range']['cidr'],
                          "0.0.0.0/0")

    def test_create_with_invalid_group_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "group_id": "invalid",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_empty_group_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "group_id": "invalid",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_with_invalid_group_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "group_id": "222222",
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_create_rule_with_same_group_parent_id_json(self):
        rules = {
              "security_group_rule": {
                  "ip_protocol": "tcp",
                  "from_port": "22",
                  "to_port": "22",
                  "group_id": "%s" % self.parent_security_group['id'],
                  "parent_group_id": "%s" % self.parent_security_group['id'],
               }
            }

        response = self._create_security_group_rule_json(rules)
        self.assertEquals(response.status_int, 400)

    def test_delete(self):
        response = self._delete_security_group_rule(
                                  self.security_group_rule['id'])
        self.assertEquals(response.status_int, 202)

        response = self._delete_security_group_rule(
                                  self.security_group_rule['id'])
        self.assertEquals(response.status_int, 404)

    def test_delete_invalid_rule_id(self):
        response = self._delete_security_group_rule('invalid')
        self.assertEquals(response.status_int, 400)

    def test_delete_non_existing_rule_id(self):
        response = self._delete_security_group_rule(22222222222222)
        self.assertEquals(response.status_int, 404)


class TestSecurityGroupRulesXMLDeserializer(unittest.TestCase):

    def setUp(self):
        self.deserializer = security_groups.SecurityGroupRulesXMLDeserializer()

    def test_create_request(self):
        serial_request = """
<security_group_rule>
  <parent_group_id>12</parent_group_id>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <group_id></group_id>
  <ip_protocol>tcp</ip_protocol>
  <cidr>10.0.0.0/24</cidr>
</security_group_rule>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "security_group_rule": {
                "parent_group_id": "12",
                "from_port": "22",
                "to_port": "22",
                "ip_protocol": "tcp",
                "group_id": "",
                "cidr": "10.0.0.0/24",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_protocol_request(self):
        serial_request = """
<security_group_rule>
  <parent_group_id>12</parent_group_id>
  <from_port>22</from_port>
  <to_port>22</to_port>
  <group_id></group_id>
  <cidr>10.0.0.0/24</cidr>
</security_group_rule>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "security_group_rule": {
                "parent_group_id": "12",
                "from_port": "22",
                "to_port": "22",
                "group_id": "",
                "cidr": "10.0.0.0/24",
            },
        }
        self.assertEquals(request['body'], expected)


class TestSecurityGroupXMLDeserializer(unittest.TestCase):

    def setUp(self):
        self.deserializer = security_groups.SecurityGroupXMLDeserializer()

    def test_create_request(self):
        serial_request = """
<security_group name="test">
   <description>test</description>
</security_group>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "security_group": {
                "name": "test",
                "description": "test",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_description_request(self):
        serial_request = """
<security_group name="test">
</security_group>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "security_group": {
                "name": "test",
            },
        }
        self.assertEquals(request['body'], expected)

    def test_create_no_name_request(self):
        serial_request = """
<security_group>
<description>test</description>
</security_group>"""
        request = self.deserializer.deserialize(serial_request, 'create')
        expected = {
            "security_group": {
                "description": "test",
            },
        }
        self.assertEquals(request['body'], expected)
