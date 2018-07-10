#    Copyright 2014 Red Hat, Inc.
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

from nova import exception
from nova.objects import agent as agent_obj
from nova.tests.unit.objects import test_objects


fake_agent = {
    'id': 1,
    'hypervisor': 'novavm',
    'os': 'linux',
    'architecture': 'DISC',
    'version': '1.0',
    'url': 'http://openstack.org/novavm/agents/novavm_agent_v1.0.rpm',
    'md5hash': '8cb151f3adc23a92db8ddbe084796823',
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
}


class _TestAgent(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    @mock.patch('nova.db.api.agent_build_get_by_triple')
    def test_get_by_triple(self, mock_get):
        mock_get.return_value = fake_agent
        agent = agent_obj.Agent.get_by_triple(self.context,
                                              'novavm', 'linux', 'DISC')
        self._compare(self, fake_agent, agent)

    @mock.patch('nova.db.api.agent_build_get_by_triple')
    def test_get_by_triple_none(self, mock_get):
        mock_get.return_value = None
        agent = agent_obj.Agent.get_by_triple(self.context,
                                              'novavm', 'linux', 'DISC')
        self.assertIsNone(agent)

    @mock.patch('nova.db.api.agent_build_create')
    def test_create(self, mock_create):
        mock_create.return_value = fake_agent
        agent = agent_obj.Agent(context=self.context)
        agent.hypervisor = 'novavm'
        agent.create()
        mock_create.assert_called_once_with(self.context,
                                            {'hypervisor': 'novavm'})
        self._compare(self, fake_agent, agent)

    @mock.patch('nova.db.api.agent_build_create')
    def test_create_with_id(self, mock_create):
        agent = agent_obj.Agent(context=self.context, id=123)
        self.assertRaises(exception.ObjectActionError, agent.create)
        self.assertFalse(mock_create.called)

    @mock.patch('nova.db.api.agent_build_destroy')
    def test_destroy(self, mock_destroy):
        agent = agent_obj.Agent(context=self.context, id=123)
        agent.destroy()
        mock_destroy.assert_called_once_with(self.context, 123)

    @mock.patch('nova.db.api.agent_build_update')
    def test_save(self, mock_update):
        mock_update.return_value = fake_agent
        agent = agent_obj.Agent(context=self.context, id=123)
        agent.obj_reset_changes()
        agent.hypervisor = 'novavm'
        agent.save()
        mock_update.assert_called_once_with(self.context, 123,
                                            {'hypervisor': 'novavm'})

    @mock.patch('nova.db.api.agent_build_get_all')
    def test_get_all(self, mock_get_all):
        mock_get_all.return_value = [fake_agent]
        agents = agent_obj.AgentList.get_all(self.context, hypervisor='novavm')
        self.assertEqual(1, len(agents))
        self._compare(self, fake_agent, agents[0])
        mock_get_all.assert_called_once_with(self.context, hypervisor='novavm')


class TestAgent(test_objects._LocalTest, _TestAgent):
    pass


class TestAgentRemote(test_objects._RemoteTest, _TestAgent):
    pass
