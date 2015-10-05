#    Copyright 2013 IBM Corp.
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

from oslo_utils import timeutils

from nova import db
from nova import objects
from nova.objects import base
from nova.objects import fields


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceAction(base.NovaPersistentObject, base.NovaObject,
                     base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    VERSION = '1.1'

    fields = {
        'id': fields.IntegerField(),
        'action': fields.StringField(nullable=True),
        'instance_uuid': fields.UUIDField(nullable=True),
        'request_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        'start_time': fields.DateTimeField(nullable=True),
        'finish_time': fields.DateTimeField(nullable=True),
        'message': fields.StringField(nullable=True),
        }

    @staticmethod
    def _from_db_object(context, action, db_action):
        for field in action.fields:
            action[field] = db_action[field]
        action._context = context
        action.obj_reset_changes()
        return action

    @staticmethod
    def pack_action_start(context, instance_uuid, action_name):
        values = {'request_id': context.request_id,
                  'instance_uuid': instance_uuid,
                  'user_id': context.user_id,
                  'project_id': context.project_id,
                  'action': action_name,
                  'start_time': context.timestamp}
        return values

    @staticmethod
    def pack_action_finish(context, instance_uuid):
        values = {'request_id': context.request_id,
                  'instance_uuid': instance_uuid,
                  'finish_time': timeutils.utcnow()}
        return values

    @base.remotable_classmethod
    def get_by_request_id(cls, context, instance_uuid, request_id):
        db_action = db.action_get_by_request_id(context, instance_uuid,
                                                request_id)
        if db_action:
            return cls._from_db_object(context, cls(), db_action)

    @base.remotable_classmethod
    def action_start(cls, context, instance_uuid, action_name,
                     want_result=True):
        values = cls.pack_action_start(context, instance_uuid, action_name)
        db_action = db.action_start(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_action)

    @base.remotable_classmethod
    def action_finish(cls, context, instance_uuid, want_result=True):
        values = cls.pack_action_finish(context, instance_uuid)
        db_action = db.action_finish(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_action)

    @base.remotable
    def finish(self):
        values = self.pack_action_finish(self._context, self.instance_uuid)
        db_action = db.action_finish(self._context, values)
        self._from_db_object(self._context, self, db_action)


@base.NovaObjectRegistry.register
class InstanceActionList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              InstanceAction <= version 1.1
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('InstanceAction'),
        }

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_actions = db.actions_get(context, instance_uuid)
        return base.obj_make_list(context, cls(), InstanceAction, db_actions)


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceActionEvent(base.NovaPersistentObject, base.NovaObject,
                          base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: event_finish_with_failure decorated with serialize_args
    VERSION = '1.1'
    fields = {
        'id': fields.IntegerField(),
        'event': fields.StringField(nullable=True),
        'action_id': fields.IntegerField(nullable=True),
        'start_time': fields.DateTimeField(nullable=True),
        'finish_time': fields.DateTimeField(nullable=True),
        'result': fields.StringField(nullable=True),
        'traceback': fields.StringField(nullable=True),
        }

    @staticmethod
    def _from_db_object(context, event, db_event):
        for field in event.fields:
            event[field] = db_event[field]
        event._context = context
        event.obj_reset_changes()
        return event

    @staticmethod
    def pack_action_event_start(context, instance_uuid, event_name):
        values = {'event': event_name,
                  'instance_uuid': instance_uuid,
                  'request_id': context.request_id,
                  'start_time': timeutils.utcnow()}
        return values

    @staticmethod
    def pack_action_event_finish(context, instance_uuid, event_name,
                                 exc_val=None, exc_tb=None):
        values = {'event': event_name,
                  'instance_uuid': instance_uuid,
                  'request_id': context.request_id,
                  'finish_time': timeutils.utcnow()}
        if exc_tb is None:
            values['result'] = 'Success'
        else:
            values['result'] = 'Error'
            values['message'] = exc_val
            values['traceback'] = exc_tb
        return values

    @base.remotable_classmethod
    def get_by_id(cls, context, action_id, event_id):
        db_event = db.action_event_get_by_id(context, action_id, event_id)
        return cls._from_db_object(context, cls(), db_event)

    @base.remotable_classmethod
    def event_start(cls, context, instance_uuid, event_name, want_result=True):
        values = cls.pack_action_event_start(context, instance_uuid,
                                             event_name)
        db_event = db.action_event_start(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_event)

    @base.serialize_args
    @base.remotable_classmethod
    def event_finish_with_failure(cls, context, instance_uuid, event_name,
                                  exc_val=None, exc_tb=None, want_result=None):
        values = cls.pack_action_event_finish(context, instance_uuid,
                                              event_name, exc_val=exc_val,
                                              exc_tb=exc_tb)
        db_event = db.action_event_finish(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_event)

    @base.remotable_classmethod
    def event_finish(cls, context, instance_uuid, event_name,
                     want_result=True):
        return cls.event_finish_with_failure(context, instance_uuid,
                                             event_name, exc_val=None,
                                             exc_tb=None,
                                             want_result=want_result)

    @base.remotable
    def finish_with_failure(self, exc_val, exc_tb):
        values = self.pack_action_event_finish(self._context,
                                               self.instance_uuid,
                                               self.event, exc_val=exc_val,
                                               exc_tb=exc_tb)
        db_event = db.action_event_finish(self._context, values)
        self._from_db_object(self._context, self, db_event)

    @base.remotable
    def finish(self):
        self.finish_with_failure(self._context, exc_val=None, exc_tb=None)


@base.NovaObjectRegistry.register
class InstanceActionEventList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.1'
    fields = {
        'objects': fields.ListOfObjectsField('InstanceActionEvent'),
        }

    @base.remotable_classmethod
    def get_by_action(cls, context, action_id):
        db_events = db.action_events_get(context, action_id)
        return base.obj_make_list(context, cls(context),
                                  objects.InstanceActionEvent, db_events)
