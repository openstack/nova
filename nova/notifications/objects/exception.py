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

import inspect
import traceback as tb

from nova.notifications.objects import base
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class ExceptionPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 1.1: Add traceback field to ExceptionPayload
    VERSION = '1.1'
    fields = {
        'module_name': fields.StringField(),
        'function_name': fields.StringField(),
        'exception': fields.StringField(),
        'exception_message': fields.StringField(),
        'traceback': fields.StringField()
    }

    def __init__(self, module_name, function_name, exception,
                 exception_message, traceback):
        super(ExceptionPayload, self).__init__()
        self.module_name = module_name
        self.function_name = function_name
        self.exception = exception
        self.exception_message = exception_message
        self.traceback = traceback

    @classmethod
    def from_exception(cls, fault: Exception):
        traceback = fault.__traceback__

        # NOTE(stephenfin): inspect.trace() will only return something if we're
        # inside the scope of an exception handler. If we are not, we fallback
        # to extracting information from the traceback. This is lossy, since
        # the stack stops at the exception handler, not the exception raise.
        # Check the inspect docs for more information.
        #
        # https://docs.python.org/3/library/inspect.html#types-and-members
        trace = inspect.trace()
        if trace:
            module = inspect.getmodule(trace[-1][0])
            function_name = trace[-1][3]
        else:
            module = inspect.getmodule(traceback)
            function_name = traceback.tb_frame.f_code.co_name

        module_name = module.__name__ if module else 'unknown'

        # TODO(gibi): apply strutils.mask_password on exception_message and
        # consider emitting the exception_message only if the safe flag is
        # true in the exception like in the REST API
        return cls(
            function_name=function_name,
            module_name=module_name,
            exception=fault.__class__.__name__,
            exception_message=str(fault),
            # NOTE(stephenfin): the first argument to format_exception is
            # ignored since Python 3.5
            traceback=','.join(tb.format_exception(None, fault, traceback)),
        )


@base.notification_sample('compute-exception.json')
@nova_base.NovaObjectRegistry.register_notification
class ExceptionNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'payload': fields.ObjectField('ExceptionPayload')
    }
