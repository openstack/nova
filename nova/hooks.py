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

NOTE: as of Nova 13.0 hooks are DEPRECATED and will be removed in the
near future. You should not build any new code using this facility.

Any method may have the 'add_hook' decorator applied, which yields the
ability to invoke Hook objects before or after the method. (i.e. pre and
post)

Hook objects are loaded by HookLoaders.  Each named hook may invoke multiple
Hooks.

Example Hook object::

    | class MyHook(object):
    |    def pre(self, *args, **kwargs):
    |       # do stuff before wrapped callable runs
    |
    |   def post(self, rv, *args, **kwargs):
    |       # do stuff after wrapped callable runs

Example Hook object with function parameters::

    | class MyHookWithFunction(object):
    |   def pre(self, f, *args, **kwargs):
    |       # do stuff with wrapped function info
    |   def post(self, f, *args, **kwargs):
    |       # do stuff with wrapped function info

"""

import functools

from oslo_log import log as logging
import stevedore

from nova.i18n import _, _LE, _LW

LOG = logging.getLogger(__name__)
NS = 'nova.hooks'

_HOOKS = {}  # hook name => hook manager


class FatalHookException(Exception):
    """Exception which should be raised by hooks to indicate that normal
    execution of the hooked function should be terminated. Raised exception
    will be logged and reraised.
    """
    pass


class HookManager(stevedore.hook.HookManager):
    def __init__(self, name):
        """Invoke_on_load creates an instance of the Hook class

        :param name: The name of the hooks to load.
        :type name: str
        """
        super(HookManager, self).__init__(NS, name, invoke_on_load=True)

    def _run(self, name, method_type, args, kwargs, func=None):
        if method_type not in ('pre', 'post'):
            msg = _("Wrong type of hook method. "
                    "Only 'pre' and 'post' type allowed")
            raise ValueError(msg)

        for e in self.extensions:
            obj = e.obj
            hook_method = getattr(obj, method_type, None)
            if hook_method:
                LOG.warning(_LW("Hooks are deprecated as of Nova 13.0 and "
                                "will be removed in a future release"))
                LOG.debug("Running %(name)s %(type)s-hook: %(obj)s",
                          {'name': name, 'type': method_type, 'obj': obj})
                try:
                    if func:
                        hook_method(func, *args, **kwargs)
                    else:
                        hook_method(*args, **kwargs)
                except FatalHookException:
                    msg = _LE("Fatal Exception running %(name)s "
                              "%(type)s-hook: %(obj)s")
                    LOG.exception(msg, {'name': name, 'type': method_type,
                                        'obj': obj})
                    raise
                except Exception:
                    msg = _LE("Exception running %(name)s "
                              "%(type)s-hook: %(obj)s")
                    LOG.exception(msg, {'name': name, 'type': method_type,
                                        'obj': obj})

    def run_pre(self, name, args, kwargs, f=None):
        """Execute optional pre methods of loaded hooks.

        :param name: The name of the loaded hooks.
        :param args: Positional arguments which would be transmitted into
                     all pre methods of loaded hooks.
        :param kwargs: Keyword args which would be transmitted into all pre
                       methods of loaded hooks.
        :param f: Target function.
        """
        self._run(name=name, method_type='pre', args=args, kwargs=kwargs,
                  func=f)

    def run_post(self, name, rv, args, kwargs, f=None):
        """Execute optional post methods of loaded hooks.

        :param name: The name of the loaded hooks.
        :param rv: Return values of target method call.
        :param args: Positional arguments which would be transmitted into
                     all post methods of loaded hooks.
        :param kwargs: Keyword args which would be transmitted into all post
                       methods of loaded hooks.
        :param f: Target function.
        """
        self._run(name=name, method_type='post', args=(rv,) + args,
                  kwargs=kwargs, func=f)


def add_hook(name, pass_function=False):
    """Execute optional pre and post methods around the decorated
    function.  This is useful for customization around callables.
    """

    def outer(f):
        f.__hook_name__ = name

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
