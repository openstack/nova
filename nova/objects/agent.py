#    Copyright 2014 Red Hat, Inc
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

from nova.db import api as db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class Agent(base.NovaPersistentObject, base.NovaObject):
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'hypervisor': fields.StringField(),
        'os': fields.StringField(),
        'architecture': fields.StringField(),
        'version': fields.StringField(),
        'url': fields.StringField(),
        'md5hash': fields.StringField(),
        }

    @staticmethod
    def _from_db_object(context, agent, db_agent):
        for name in agent.fields:
            setattr(agent, name, db_agent[name])
        agent._context = context
        agent.obj_reset_changes()
        return agent

    @base.remotable_classmethod
    def get_by_triple(cls, context, hypervisor, os, architecture):
        db_agent = db.agent_build_get_by_triple(context, hypervisor,
                                                os, architecture)
        if not db_agent:
            return None
        return cls._from_db_object(context, objects.Agent(), db_agent)

    @base.remotable
    def create(self):
        updates = self.obj_get_changes()
        if 'id' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason='Already Created')
        db_agent = db.agent_build_create(self._context, updates)
        self._from_db_object(self._context, self, db_agent)

    @base.remotable
    def destroy(self):
        db.agent_build_destroy(self._context, self.id)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        db.agent_build_update(self._context, self.id, updates)
        self.obj_reset_changes()


@base.NovaObjectRegistry.register
class AgentList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Agent'),
        }

    @base.remotable_classmethod
    def get_all(cls, context, hypervisor=None):
        db_agents = db.agent_build_get_all(context, hypervisor=hypervisor)
        return base.obj_make_list(context, cls(), objects.Agent, db_agents)
