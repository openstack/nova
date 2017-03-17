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

import functools
import inspect

from oslo_utils import excutils
import six

import nova.conf
from nova.notifications.objects import base
from nova.notifications.objects import exception
from nova.objects import fields
from nova import safe_utils

CONF = nova.conf.CONF


def _emit_exception_notification(notifier, context, ex, function_name, args,
                                 binary):
    _emit_legacy_exception_notification(notifier, context, ex, function_name,
                                        args)
    _emit_versioned_exception_notification(context, ex, binary)


def _emit_versioned_exception_notification(context, ex, binary):
    versioned_exception_payload = exception.ExceptionPayload.from_exception(ex)
    publisher = base.NotificationPublisher(context=context, host=CONF.host,
                                           binary=binary)
    event_type = base.EventType(
            object='compute',
            action=fields.NotificationAction.EXCEPTION)
    notification = exception.ExceptionNotification(
        publisher=publisher,
        event_type=event_type,
        priority=fields.NotificationPriority.ERROR,
        payload=versioned_exception_payload)
    notification.emit(context)


def _emit_legacy_exception_notification(notifier, context, ex, function_name,
                                       args):
    payload = dict(exception=ex, args=args)
    notifier.error(context, function_name, payload)


def wrap_exception(notifier=None, get_notifier=None, binary=None):
    """This decorator wraps a method to catch any exceptions that may
    get thrown. It also optionally sends the exception to the notification
    system.
    """
    def inner(f):
        def wrapped(self, context, *args, **kw):
            # Don't store self or context in the payload, it now seems to
            # contain confidential information.
            try:
                return f(self, context, *args, **kw)
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    if notifier or get_notifier:
                        call_dict = _get_call_dict(
                            f, self, context, *args, **kw)
                        function_name = f.__name__
                        _emit_exception_notification(
                            notifier or get_notifier(), context, e,
                            function_name, call_dict, binary)

        return functools.wraps(f)(wrapped)
    return inner


def _get_call_dict(function, self, context, *args, **kw):
    wrapped_func = safe_utils.get_wrapped_function(function)

    call_dict = inspect.getcallargs(wrapped_func, self,
                                    context, *args, **kw)
    # self can't be serialized and shouldn't be in the
    # payload
    call_dict.pop('self', None)
    # NOTE(gibi) remove context as well as it contains sensitive information
    # and it can also contain circular references
    call_dict.pop('context', None)
    return _cleanse_dict(call_dict)


def _cleanse_dict(original):
    """Strip all admin_password, new_pass, rescue_pass keys from a dict."""
    return {k: v for k, v in six.iteritems(original) if "_pass" not in k}
