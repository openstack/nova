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
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class TaskLog(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'task_name': fields.StringField(),
        'state': fields.StringField(read_only=True),
        'host': fields.StringField(),
        'period_beginning': fields.DateTimeField(),
        'period_ending': fields.DateTimeField(),
        'message': fields.StringField(),
        'task_items': fields.IntegerField(),
        'errors': fields.IntegerField(),
        }

    @staticmethod
    def _from_db_object(context, task_log, db_task_log):
        for field in task_log.fields:
            setattr(task_log, field, db_task_log[field])
        task_log._context = context
        task_log.obj_reset_changes()
        return task_log

    @base.serialize_args
    @base.remotable_classmethod
    def get(cls, context, task_name, period_beginning, period_ending, host,
            state=None):
        db_task_log = db.task_log_get(context, task_name, period_beginning,
                                      period_ending, host, state=state)
        if db_task_log:
            return cls._from_db_object(context, cls(context), db_task_log)

    @base.remotable
    def begin_task(self):
        db.task_log_begin_task(
            self._context, self.task_name, self.period_beginning,
            self.period_ending, self.host, task_items=self.task_items,
            message=self.message)

    @base.remotable
    def end_task(self):
        db.task_log_end_task(
            self._context, self.task_name, self.period_beginning,
            self.period_ending, self.host, errors=self.errors,
            message=self.message)


@base.NovaObjectRegistry.register
class TaskLogList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('TaskLog'),
    }

    @base.serialize_args
    @base.remotable_classmethod
    def get_all(cls, context, task_name, period_beginning, period_ending,
                host=None, state=None):
        db_task_logs = db.task_log_get_all(context, task_name,
                                           period_beginning, period_ending,
                                           host=host, state=state)
        return base.obj_make_list(context, cls(context), TaskLog, db_task_logs)
