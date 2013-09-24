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
from webob import exc

from nova.api.openstack.compute.plugins.v3 import agents
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova import test

fake_agents_list = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'xxx://xxxx/xxx/xxx',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'xxx://xxxx/xxx/xxx1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'id': 2},
                    {'hypervisor': 'xen', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'xxx://xxxx/xxx/xxx2',
                     'md5hash': 'add6bb58e139be103324d04d82d8f547',
                     'id': 3},
                    {'hypervisor': 'xen', 'os': 'win',
                     'architecture': 'power',
                     'version': '7.0',
                     'url': 'xxx://xxxx/xxx/xxx3',
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


class FakeRequest(object):
    environ = {"nova.context": context.get_admin_context()}
    GET = {}


class FakeRequestWithHypervisor(object):
    environ = {"nova.context": context.get_admin_context()}
    GET = {'hypervisor': 'kvm'}


def fake_agent_build_create_with_exited_agent(context, values):
    raise exception.AgentBuildExists(**values)


class AgentsTest(test.NoDBTestCase):

    def setUp(self):
        super(AgentsTest, self).setUp()

        self.stubs.Set(db, "agent_build_get_all",
                       fake_agent_build_get_all)
        self.stubs.Set(db, "agent_build_update",
                       fake_agent_build_update)
        self.stubs.Set(db, "agent_build_destroy",
                       fake_agent_build_destroy)
        self.stubs.Set(db, "agent_build_create",
                       fake_agent_build_create)
        self.context = context.get_admin_context()
        self.controller = agents.AgentController()

    def test_agents_create(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        response = {'agent': {'hypervisor': 'kvm',
                    'os': 'win',
                    'architecture': 'x86',
                    'version': '7.0',
                    'url': 'xxx://xxxx/xxx/xxx',
                    'md5hash': 'add6bb58e139be103324d04d82d8f545',
                    'agent_id': 1}}
        res_dict = self.controller.create(req, body)
        self.assertEqual(res_dict, response)
        self.assertEqual(self.controller.create.wsgi_code, 201)

    def test_agents_create_with_existed_agent(self):
        self.stubs.Set(db, 'agent_build_create',
                       fake_agent_build_create_with_exited_agent)
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPConflict, self.controller.create, req, body)

    def test_agents_create_without_md5hash(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_without_url(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_without_version(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'architecture': 'x86',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_without_architecture(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'os': 'win',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_without_os(self):
        req = FakeRequest()
        body = {'agent': {'hypervisor': 'kvm',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_without_hypervisor(self):
        req = FakeRequest()
        body = {'agent': {'os': 'win',
                'architecture': 'x86',
                'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_with_wrong_type(self):
        req = FakeRequest()
        body = {'agent': None}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_create_with_empty_type(self):
        req = FakeRequest()
        body = {}
        self.assertRaises(exc.HTTPBadRequest, self.controller.create,
                          req, body)

    def test_agents_delete(self):
        req = FakeRequest()
        self.controller.delete(req, 1)

    def test_agents_list(self):
        req = FakeRequest()
        res_dict = self.controller.index(req)
        agents_list = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'xxx://xxxx/xxx/xxx',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'xxx://xxxx/xxx/xxx1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    {'hypervisor': 'xen', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'xxx://xxxx/xxx/xxx2',
                     'md5hash': 'add6bb58e139be103324d04d82d8f547',
                     'agent_id': 3},
                    {'hypervisor': 'xen', 'os': 'win',
                     'architecture': 'power',
                     'version': '7.0',
                     'url': 'xxx://xxxx/xxx/xxx3',
                     'md5hash': 'add6bb58e139be103324d04d82d8f548',
                     'agent_id': 4},
                    ]
        self.assertEqual(res_dict, {'agents': agents_list})

    def test_agents_list_with_hypervisor(self):
        req = FakeRequestWithHypervisor()
        res_dict = self.controller.index(req)
        response = [{'hypervisor': 'kvm', 'os': 'win',
                     'architecture': 'x86',
                     'version': '7.0',
                     'url': 'xxx://xxxx/xxx/xxx',
                     'md5hash': 'add6bb58e139be103324d04d82d8f545',
                     'agent_id': 1},
                    {'hypervisor': 'kvm', 'os': 'linux',
                     'architecture': 'x86',
                     'version': '16.0',
                     'url': 'xxx://xxxx/xxx/xxx1',
                     'md5hash': 'add6bb58e139be103324d04d82d8f546',
                     'agent_id': 2},
                    ]
        self.assertEqual(res_dict, {'agents': response})

    def test_agents_update(self):
        req = FakeRequest()
        body = {'agent': {'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        response = {'agent': {'agent_id': 1,
                    'version': '7.0',
                    'url': 'xxx://xxxx/xxx/xxx',
                    'md5hash': 'add6bb58e139be103324d04d82d8f545'}}
        res_dict = self.controller.update(req, 1, body)
        self.assertEqual(res_dict, response)

    def test_agents_update_without_md5hash(self):
        req = FakeRequest()
        body = {'agent': {'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, 1, body)

    def test_agents_update_without_url(self):
        req = FakeRequest()
        body = {'agent': {'version': '7.0'}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, 1, body)

    def test_agents_update_without_version(self):
        req = FakeRequest()
        body = {'agent': {}}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, 1, body)

    def test_agents_update_with_wrong_type(self):
        req = FakeRequest()
        body = {'agent': None}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, 1, body)

    def test_agents_update_with_empty(self):
        req = FakeRequest()
        body = {}
        self.assertRaises(exc.HTTPBadRequest, self.controller.update,
                          req, 1, body)
