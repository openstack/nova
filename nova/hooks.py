# Copyright (c) 2012 OpenStack Foundation
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

"""Decorator and config option definitions for adding custom code (hooks)
around callables.

Any method may have the 'add_hook' decorator applied, which yields the
ability to invoke Hook objects before or after the method. (i.e. pre and
post)

Hook objects are loaded by HookLoaders.  Each named hook may invoke multiple
Hooks.

Example Hook object:

class MyHook(object):
    def pre(self, *args, **kwargs):
        # do stuff before wrapped callable runs

    def post(self, rv, *args, **kwargs):
        # do stuff after wrapped callable runs

Example Hook object with function parameters:

class MyHookWithFunction(object):
    def pre(self, f, *args, **kwargs):
        # do stuff with wrapped function info
    def post(self, f, *args, **kwards):
        # do stuff with wrapped function info

"""

import functools

import stevedore

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
NS = 'nova.hooks'

_HOOKS = {}  # hook name => hook manager


class HookManager(stevedore.hook.HookManager):
    def __init__(self, name):
        # invoke_on_load creates an instance of the Hook class
        super(HookManager, self).__init__(NS, name, invoke_on_load=True)

    def run_pre(self, name, args, kwargs, f=None):
        for e in self.extensions:
            obj = e.obj
            pre = getattr(obj, 'pre', None)
            if pre:
                LOG.debug(_("Running %(name)s pre-hook: %(obj)s"),
                          {'name': name, 'obj': obj})
                if f:
                    pre(f, *args, **kwargs)
                else:
                    pre(*args, **kwargs)

    def run_post(self, name, rv, args, kwargs, f=None):
        for e in reversed(self.extensions):
            obj = e.obj
            post = getattr(obj, 'post', None)
            if post:
                LOG.debug(_("Running %(name)s post-hook: %(obj)s"),
                          {'name': name, 'obj': obj})
                if f:
                    post(f, rv, *args, **kwargs)
                else:
                    post(rv, *args, **kwargs)


def add_hook(name, pass_function=False):
    """Execute optional pre and post methods around the decorated
    function.  This is useful for customization around callables.
    """

    def outer(f):
        @functools.wraps(f)
        def inner(*args, **kwargs):
            manager = _HOOKS.setdefault(name, HookManager(name))

            function = None
            if pass_function:
                function = f

            manager.run_pre(name, args, kwargs, f=function)
            rv = f(*args, **kwargs)
            manager.run_post(name, rv, args, kwargs, f=function)

            return rv

        return inner
    return outer


def reset():
    """Clear loaded hooks."""
    _HOOKS.clear()
