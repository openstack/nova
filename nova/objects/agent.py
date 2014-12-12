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

from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


# TODO(berrange): Remove NovaObjectDictCompat
class Agent(base.NovaPersistentObject, base.NovaObject,
            base.NovaObjectDictCompat):
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
            agent[name] = db_agent[name]
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
    def create(self, context):
        updates = self.obj_get_changes()
        if 'id' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason='Already Created')
        db_agent = db.agent_build_create(context, updates)
        self._from_db_object(context, self, db_agent)

    @base.remotable
    def destroy(self, context):
        db.agent_build_destroy(context, self.id)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        db.agent_build_update(context, self.id, updates)
        self.obj_reset_changes()


class AgentList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('Agent'),
        }
    child_versions = {
        '1.0': '1.0',
        }

    @base.remotable_classmethod
    def get_all(cls, context, hypervisor=None):
        db_agents = db.agent_build_get_all(context, hypervisor=hypervisor)
        return base.obj_make_list(context, cls(), objects.Agent, db_agents)
