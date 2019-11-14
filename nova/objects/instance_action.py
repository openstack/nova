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
from oslo_utils import versionutils
import six

from nova.compute import utils as compute_utils
from nova.db import api as db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceAction(base.NovaPersistentObject, base.NovaObject,
                     base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Add create() method.
    VERSION = '1.2'

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
                  'start_time': context.timestamp,
                  'updated_at': context.timestamp}
        return values

    @staticmethod
    def pack_action_finish(context, instance_uuid):
        utcnow = timeutils.utcnow()
        values = {'request_id': context.request_id,
                  'instance_uuid': instance_uuid,
                  'finish_time': utcnow,
                  'updated_at': utcnow}
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

    # NOTE(mriedem): In most cases, the action_start() method should be used
    # to create new InstanceAction records. This method should only be used
    # in specific exceptional cases like when cloning actions from one cell
    # database to another.
    @base.remotable
    def create(self):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_action = db.action_start(self._context, updates)
        self._from_db_object(self._context, self, db_action)


@base.NovaObjectRegistry.register
class InstanceActionList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: get_by_instance_uuid added pagination and filters support
    VERSION = '1.1'
    fields = {
        'objects': fields.ListOfObjectsField('InstanceAction'),
        }

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid, limit=None,
                             marker=None, filters=None):
        db_actions = db.actions_get(
            context, instance_uuid, limit, marker, filters)
        return base.obj_make_list(context, cls(), InstanceAction, db_actions)


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceActionEvent(base.NovaPersistentObject, base.NovaObject,
                          base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: event_finish_with_failure decorated with serialize_args
    # Version 1.2: Add 'host' field
    # Version 1.3: Add create() method.
    # Version 1.4: Added 'details' field.
    VERSION = '1.4'
    fields = {
        'id': fields.IntegerField(),
        'event': fields.StringField(nullable=True),
        'action_id': fields.IntegerField(nullable=True),
        'start_time': fields.DateTimeField(nullable=True),
        'finish_time': fields.DateTimeField(nullable=True),
        'result': fields.StringField(nullable=True),
        'traceback': fields.StringField(nullable=True),
        'host': fields.StringField(nullable=True),
        'details': fields.StringField(nullable=True)
        }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 4) and 'details' in primitive:
            del primitive['details']
        if target_version < (1, 2) and 'host' in primitive:
            del primitive['host']

    @staticmethod
    def _from_db_object(context, event, db_event):
        for field in event.fields:
            event[field] = db_event[field]
        event._context = context
        event.obj_reset_changes()
        return event

    @staticmethod
    def pack_action_event_start(context, instance_uuid, event_name,
                                host=None):
        values = {'event': event_name,
                  'instance_uuid': instance_uuid,
                  'request_id': context.request_id,
                  'start_time': timeutils.utcnow(),
                  'host': host}
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
            # Store the details using the same logic as storing an instance
            # fault message.
            if exc_val:
                # If we got a string for exc_val it's probably because of
                # the serialize_args decorator on event_finish_with_failure
                # so pass that as the message to exception_to_dict otherwise
                # the details will just the exception class name since it
                # cannot format the message as a NovaException.
                message = (
                    exc_val if isinstance(exc_val, six.string_types) else None)
                values['details'] = compute_utils.exception_to_dict(
                    exc_val, message=message)['message']
            values['traceback'] = exc_tb
        return values

    @base.remotable_classmethod
    def get_by_id(cls, context, action_id, event_id):
        db_event = db.action_event_get_by_id(context, action_id, event_id)
        return cls._from_db_object(context, cls(), db_event)

    @base.remotable_classmethod
    def event_start(cls, context, instance_uuid, event_name, want_result=True,
                    host=None):
        values = cls.pack_action_event_start(context, instance_uuid,
                                             event_name, host=host)
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

    # NOTE(mriedem): In most cases, the event_start() method should be used
    # to create new InstanceActionEvent records. This method should only be
    # used in specific exceptional cases like when cloning events from one cell
    # database to another.
    @base.remotable
    def create(self, instance_uuid, request_id):
        if 'id' in self:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        # The instance_uuid and request_id uniquely identify the "parent"
        # InstanceAction for this event and are used in action_event_start().
        # TODO(mriedem): This could be optimized if we just didn't use
        # db.action_event_start and inserted the record ourselves and passed
        # in the action_id.
        updates['instance_uuid'] = instance_uuid
        updates['request_id'] = request_id
        db_event = db.action_event_start(self._context, updates)
        self._from_db_object(self._context, self, db_event)


@base.NovaObjectRegistry.register
class InstanceActionEventList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: InstanceActionEvent <= 1.1
    VERSION = '1.1'
    fields = {
        'objects': fields.ListOfObjectsField('InstanceActionEvent'),
        }

    @base.remotable_classmethod
    def get_by_action(cls, context, action_id):
        db_events = db.action_events_get(context, action_id)
        return base.obj_make_list(context, cls(context),
                                  objects.InstanceActionEvent, db_events)
