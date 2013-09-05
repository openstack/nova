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

from nova.compute import utils as compute_utils
from nova import db
from nova.objects import base
from nova.objects import utils


class InstanceAction(base.NovaObject):
    fields = {
        'id': int,
        'action': utils.str_or_none,
        'instance_uuid': utils.str_or_none,
        'request_id': utils.str_or_none,
        'user_id': utils.str_or_none,
        'project_id': utils.str_or_none,
        'start_time': utils.datetime_or_none,
        'finish_time': utils.datetime_or_none,
        'message': utils.str_or_none,
        }

    _attr_start_time_to_primitive = utils.dt_serializer('start_time')
    _attr_finish_time_to_primitive = utils.dt_serializer('finish_time')
    _attr_start_time_from_primitive = utils.dt_deserializer
    _attr_finish_time_from_primitive = utils.dt_deserializer

    @staticmethod
    def _from_db_object(context, action, db_action):
        for field in action.fields:
            action[field] = db_action[field]
        action._context = context
        action.obj_reset_changes()
        return action

    @base.remotable_classmethod
    def get_by_request_id(cls, context, instance_uuid, request_id):
        db_action = db.action_get_by_request_id(context, instance_uuid,
                                                request_id)
        if db_action:
            return cls._from_db_object(context, cls(), db_action)

    # NOTE(danms): Eventually the compute_utils.*action* methods
    # can be here, I think

    @base.remotable_classmethod
    def action_start(cls, context, instance_uuid, action_name,
                     want_result=True):
        values = compute_utils.pack_action_start(context, instance_uuid,
                                                 action_name)
        db_action = db.action_start(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_action)

    @base.remotable_classmethod
    def action_finish(cls, context, instance_uuid, want_result=True):
        values = compute_utils.pack_action_finish(context, instance_uuid)
        db_action = db.action_finish(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_action)

    @base.remotable
    def finish(self, context):
        values = compute_utils.pack_action_finish(context, self.instance_uuid)
        db_action = db.action_finish(context, values)
        self._from_db_object(context, self, db_action)


class InstanceActionList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_actions = db.actions_get(context, instance_uuid)
        return base.obj_make_list(context, cls(), InstanceAction, db_actions)


class InstanceActionEvent(base.NovaObject):
    fields = {
        'id': int,
        'event': utils.str_or_none,
        'action_id': utils.int_or_none,
        'start_time': utils.datetime_or_none,
        'finish_time': utils.datetime_or_none,
        'result': utils.str_or_none,
        'traceback': utils.str_or_none,
        }

    _attr_start_time_to_primitive = utils.dt_serializer('start_time')
    _attr_finish_time_to_primitive = utils.dt_serializer('finish_time')
    _attr_start_time_from_primitive = utils.dt_deserializer
    _attr_finish_time_from_primitive = utils.dt_deserializer

    @staticmethod
    def _from_db_object(context, event, db_event):
        for field in event.fields:
            event[field] = db_event[field]
        event._context = context
        event.obj_reset_changes()
        return event

    @base.remotable_classmethod
    def get_by_id(cls, context, action_id, event_id):
        db_event = db.action_event_get_by_id(context, action_id, event_id)
        return cls._from_db_object(context, cls(), db_event)

    @base.remotable_classmethod
    def event_start(cls, context, instance_uuid, event_name, want_result=True):
        values = compute_utils.pack_action_event_start(context, instance_uuid,
                                                       event_name)
        db_event = db.action_event_start(context, values)
        if want_result:
            return cls._from_db_object(context, cls(), db_event)

    @base.remotable_classmethod
    def event_finish_with_failure(cls, context, instance_uuid, event_name,
                                  exc_val=None, exc_tb=None, want_result=None):
        values = compute_utils.pack_action_event_finish(context, instance_uuid,
                                                        event_name,
                                                        exc_val=exc_val,
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
    def finish_with_failure(self, context, exc_val, exc_tb):
        values = compute_utils.pack_action_event_finish(context,
                                                        self.instance_uuid,
                                                        self.event,
                                                        exc_val=exc_val,
                                                        exc_tb=exc_tb)
        db_event = db.action_event_finish(context, values)
        self._from_db_object(context, self, db_event)

    @base.remotable
    def finish(self, context):
        self.finish_with_failure(context, exc_val=None, exc_tb=None)


class InstanceActionEventList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_action(cls, context, action_id):
        db_events = db.action_events_get(context, action_id)
        return base.obj_make_list(context, cls(), InstanceActionEvent,
                                  db_events)
