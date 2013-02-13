# vim: tabstop=4 shiftwidth=4 softtabstop=4


# Copyright (c) 2013 OpenStack, LLC.
# All Rights Reserved.
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

"""Common DB layer decorators."""

from nova import db
from nova import exception


def _is_context_like(obj):
    try:
        obj.is_admin
        obj.user_id
        obj.project_id
    except AttributeError:
        return False

    return True


def check_task_state(instance_ref, values):
    """If "expected_task_state" exists in values, the update can only happen
    when the task state before update matches expected_task_state. Otherwise
    a UnexpectedTaskStateError is thrown.
    """

    if "expected_task_state" in values:
        # it is not a db column so always pop out
        expected = values.pop("expected_task_state")
        if not isinstance(expected, (tuple, list, set)):
            expected = (expected,)
        actual_state = instance_ref["task_state"]
        if actual_state not in expected:
            raise exception.UnexpectedTaskStateError(actual=actual_state,
                                                     expected=expected)


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def require_context(f):
    """Decorator to require *any* user or admin context.

    This does no authorization for user or project access matching, see
    :py:func:`authorize_project_context` and
    :py:func:`authorize_user_context`.

    The first argument to the wrapped function must be the context.

    """

    def wrapper(*args, **kwargs):
        context = args[0]
        if not _is_context_like(context):
            context = args[1]

        if not context.is_admin and not is_user_context(context):
            raise exception.NotAuthorized()
        return f(*args, **kwargs)
    return wrapper
