# Copyright 2012 IBM Corp.
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
import webob.exc

from nova.api.openstack.compute import agents as agents_v21
from nova.db import api as db
from nova.db.sqlalchemy import models
from nova import exception
from nova import test
from nova.tests.unit.api.openstack import fakes

fake_agents_list = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'id': 2},
                    {'hypervisor': 'xen', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource2',
                     'md5hash': 'add6bb58e139be103324d04d82d8f547',
                     'id': 3},
                    {'hypervisor': 'xen', 'os': 'win',
                     'architecture': 'power',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource3',
                     'md5hash': 'add6bb58e139be103324d04d82d8f548',
                     'id': 4},
                    ]


def fake_agent_build_get_all(context, hypervisor):
    agent_build_all = []
    for agent in fake_agents_list:
        if hypervisor and hypervisor != agent['hypervisor']:
            continue
        agent_build_ref = models.AgentBuild()
        agent_build_ref.update(agent)
        agent_build_all.append(agent_build_ref)
    return agent_build_all


def fake_agent_build_update(context, agent_build_id, values):
    pass


def fake_agent_build_destroy(context, agent_update_id):
    pass


def fake_agent_build_create(context, values):
    values['id'] = 1
    agent_build_ref = models.AgentBuild()
    agent_build_ref.update(values)
    return agent_build_ref


class AgentsTestV21(test.NoDBTestCase):
    controller = agents_v21.AgentController()
    validation_error = exception.ValidationError

    def setUp(self):
        super(AgentsTestV21, self).setUp()

        self.stub_out("nova.db.api.agent_build_get_all",
                      fake_agent_build_get_all)
        self.stub_out("nova.db.api.agent_build_update",
                      fake_agent_build_update)
        self.stub_out("nova.db.api.agent_build_destroy",
                      fake_agent_build_destroy)
        self.stub_out("nova.db.api.agent_build_create",
                      fake_agent_build_create)
        self.req = self._get_http_request()

    def _get_http_request(self):
        return fakes.HTTPRequest.blank('')

    def test_agents_create(self):
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        response = {'agent': {'hypervisor': 'kvm',
                    'os': 'win',
                    'architecture': 'x86',
                    'version': '7.0',
                    'url': 'http://example.com/path/to/resource',
                    'md5hash': 'add6bb58e139be103324d04d82d8f545',
                    'agent_id': 1}}
        res_dict = self.controller.create(self.req, body=body)
        self.assertEqual(res_dict, response)

    def _test_agents_create_key_error(self, key):
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        body['agent'].pop(key)
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_agents_create_without_hypervisor(self):
        self._test_agents_create_key_error('hypervisor')

    def test_agents_create_without_os(self):
        self._test_agents_create_key_error('os')

    def test_agents_create_without_architecture(self):
        self._test_agents_create_key_error('architecture')

    def test_agents_create_without_version(self):
        self._test_agents_create_key_error('version')

    def test_agents_create_without_url(self):
        self._test_agents_create_key_error('url')

    def test_agents_create_without_md5hash(self):
        self._test_agents_create_key_error('md5hash')

    def test_agents_create_with_wrong_type(self):
        body = {'agent': None}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_agents_create_with_empty_type(self):
        body = {}
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_agents_create_with_existed_agent(self):
        def fake_agent_build_create_with_exited_agent(context, values):
            raise exception.AgentBuildExists(**values)

        self.stub_out('nova.db.api.agent_build_create',
                      fake_agent_build_create_with_exited_agent)
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(webob.exc.HTTPConflict, self.controller.create,
                          self.req, body=body)

    def _test_agents_create_with_invalid_length(self, key):
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        body['agent'][key] = 'x' * 256
        self.assertRaises(self.validation_error,
                          self.controller.create, self.req, body=body)

    def test_agents_create_with_invalid_length_hypervisor(self):
        self._test_agents_create_with_invalid_length('hypervisor')

    def test_agents_create_with_invalid_length_os(self):
        self._test_agents_create_with_invalid_length('os')

    def test_agents_create_with_invalid_length_architecture(self):
        self._test_agents_create_with_invalid_length('architecture')

    def test_agents_create_with_invalid_length_version(self):
        self._test_agents_create_with_invalid_length('version')

    def test_agents_create_with_invalid_length_url(self):
        self._test_agents_create_with_invalid_length('url')

    def test_agents_create_with_invalid_length_md5hash(self):
        self._test_agents_create_with_invalid_length('md5hash')

    def test_agents_delete(self):
        self.controller.delete(self.req, 1)

    def test_agents_delete_with_id_not_found(self):
        with mock.patch.object(db, 'agent_build_destroy',
            side_effect=exception.AgentBuildNotFound(id=1)):
            self.assertRaises(webob.exc.HTTPNotFound,
                              self.controller.delete, self.req, 1)

    def test_agents_delete_string_id(self):
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.delete, self.req, 'string_id')

    def _test_agents_list(self, query_string=None):
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      query_string=query_string)
        res_dict = self.controller.index(req)
        agents_list = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    {'hypervisor': 'xen', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource2',
                     'md5hash': 'add6bb58e139be103324d04d82d8f547',
                     'agent_id': 3},
                    {'hypervisor': 'xen', 'os': 'win',
                     'architecture': 'power',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource3',
                     'md5hash': 'add6bb58e139be103324d04d82d8f548',
                     'agent_id': 4},
                    ]
        self.assertEqual(res_dict, {'agents': agents_list})

    def test_agents_list(self):
        self._test_agents_list()

    def test_agents_list_with_hypervisor(self):
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      query_string='hypervisor=kvm')
        res_dict = self.controller.index(req)
        response = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    ]
        self.assertEqual(res_dict, {'agents': response})

    def test_agents_list_with_multi_hypervisor_filter(self):
        query_string = 'hypervisor=xen&hypervisor=kvm'
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      query_string=query_string)
        res_dict = self.controller.index(req)
        response = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    ]
        self.assertEqual(res_dict, {'agents': response})

    def test_agents_list_query_allow_negative_int_as_string(self):
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      query_string='hypervisor=-1')
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, {'agents': []})

    def test_agents_list_query_allow_int_as_string(self):
        req = fakes.HTTPRequest.blank('', use_admin_context=True,
                                      query_string='hypervisor=1')
        res_dict = self.controller.index(req)
        self.assertEqual(res_dict, {'agents': []})

    def test_agents_list_with_unknown_filter(self):
        query_string = 'unknown_filter=abc'
        self._test_agents_list(query_string=query_string)

    def test_agents_list_with_hypervisor_and_additional_filter(self):
        req = fakes.HTTPRequest.blank(
            '', use_admin_context=True,
            query_string='hypervisor=kvm&additional_filter=abc')
        res_dict = self.controller.index(req)
        response = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'http://example.com/path/to/resource',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'http://example.com/path/to/resource1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    ]
        self.assertEqual(res_dict, {'agents': response})

    def test_agents_update(self):
        body = {'para': {'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        response = {'agent': {'agent_id': 1,
                    'version': '7.0',
                    'url': 'http://example.com/path/to/resource',
                    'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        res_dict = self.controller.update(self.req, 1, body=body)
        self.assertEqual(res_dict, response)

    def _test_agents_update_key_error(self, key):
        body = {'para': {'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        body['para'].pop(key)
        self.assertRaises(self.validation_error,
                          self.controller.update, self.req, 1, body=body)

    def test_agents_update_without_version(self):
        self._test_agents_update_key_error('version')

    def test_agents_update_without_url(self):
        self._test_agents_update_key_error('url')

    def test_agents_update_without_md5hash(self):
        self._test_agents_update_key_error('md5hash')

    def test_agents_update_with_wrong_type(self):
        body = {'agent': None}
        self.assertRaises(self.validation_error,
                          self.controller.update, self.req, 1, body=body)

    def test_agents_update_with_empty(self):
        body = {}
        self.assertRaises(self.validation_error,
                          self.controller.update, self.req, 1, body=body)

    def test_agents_update_value_error(self):
        body = {'para': {'version': '7.0',
                'url': 1111,
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(self.validation_error,
                          self.controller.update, self.req, 1, body=body)

    def test_agents_update_with_string_id(self):
        body = {'para': {'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, self.req,
                          'string_id', body=body)

    def _test_agents_update_with_invalid_length(self, key):
        body = {'para': {'version': '7.0',
                'url': 'http://example.com/path/to/resource',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        body['para'][key] = 'x' * 256
        self.assertRaises(self.validation_error,
                          self.controller.update, self.req, 1, body=body)

    def test_agents_update_with_invalid_length_version(self):
        self._test_agents_update_with_invalid_length('version')

    def test_agents_update_with_invalid_length_url(self):
        self._test_agents_update_with_invalid_length('url')

    def test_agents_update_with_invalid_length_md5hash(self):
        self._test_agents_update_with_invalid_length('md5hash')

    def test_agents_update_with_id_not_found(self):
        with mock.patch.object(db, 'agent_build_update',
            side_effect=exception.AgentBuildNotFound(id=1)):
            body = {'para': {'version': '7.0',
                    'url': 'http://example.com/path/to/resource',
                    'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
            self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.update, self.req, 1, body=body)


class AgentsPolicyEnforcementV21(test.NoDBTestCase):

    def setUp(self):
        super(AgentsPolicyEnforcementV21, self).setUp()
        self.controller = agents_v21.AgentController()
        self.req = fakes.HTTPRequest.blank('')

    def test_create_policy_failed(self):
        rule_name = "os_compute_api:os-agents"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.create, self.req,
            body={'agent': {'hypervisor': 'kvm',
                            'os': 'win',
                            'architecture': 'x86',
                            'version': '7.0',
                            'url': 'xxx://xxxx/xxx/xxx',
                            'md5hash': 'add6bb58e139be103324d04d82d8f545'}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_index_policy_failed(self):
        rule_name = "os_compute_api:os-agents"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_policy_failed(self):
        rule_name = "os_compute_api:os-agents"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.delete, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_update_policy_failed(self):
        rule_name = "os_compute_api:os-agents"
        self.policy.set_rules({rule_name: "project_id:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.update, self.req, fakes.FAKE_UUID,
            body={'para': {'version': '7.0',
                           'url': 'xxx://xxxx/xxx/xxx',
                           'md5hash': 'add6bb58e139be103324d04d82d8f545'}})
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())
