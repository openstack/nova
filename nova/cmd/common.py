# Copyright 2016 Cloudbase Solutions Srl
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

"""
    Common functions used by different CLI interfaces.
"""

from __future__ import print_function

import argparse
import traceback

from oslo_log import log as logging
import six

import nova.conf
import nova.db.api
from nova import exception
from nova.i18n import _
from nova import utils

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def block_db_access(service_name):
    """Blocks Nova DB access."""

    class NoDB(object):
        def __getattr__(self, attr):
            return self

        def __call__(self, *args, **kwargs):
            stacktrace = "".join(traceback.format_stack())
            LOG.error('No db access allowed in %(service_name)s: '
                      '%(stacktrace)s',
                      dict(service_name=service_name, stacktrace=stacktrace))
            raise exception.DBNotAllowed(binary=service_name)

    nova.db.api.IMPL = NoDB()


def validate_args(fn, *args, **kwargs):
    """Check that the supplied args are sufficient for calling a function.

    >>> validate_args(lambda a: None)
    Traceback (most recent call last):
        ...
    MissingArgs: Missing argument(s): a
    >>> validate_args(lambda a, b, c, d: None, 0, c=1)
    Traceback (most recent call last):
        ...
    MissingArgs: Missing argument(s): b, d

    :param fn: the function to check
    :param arg: the positional arguments supplied
    :param kwargs: the keyword arguments supplied
    """
    argspec = utils.getargspec(fn)

    num_defaults = len(argspec.defaults or [])
    required_args = argspec.args[:len(argspec.args) - num_defaults]

    if six.get_method_self(fn) is not None:
        required_args.pop(0)

    missing = [arg for arg in required_args if arg not in kwargs]
    missing = missing[len(args):]
    return missing


# Decorators for actions
def args(*args, **kwargs):
    """Decorator which adds the given args and kwargs to the args list of
    the desired func's __dict__.
    """
    def _decorator(func):
        func.__dict__.setdefault('args', []).insert(0, (args, kwargs))
        return func
    return _decorator


def methods_of(obj):
    """Get all callable methods of an object that don't start with underscore

    returns a list of tuples of the form (method_name, method)
    """
    result = []
    for i in dir(obj):
        if callable(getattr(obj, i)) and not i.startswith('_'):
            result.append((i, getattr(obj, i)))
    return result


def add_command_parsers(subparsers, categories):
    """Adds command parsers to the given subparsers.

    Adds version and bash-completion parsers.
    Adds a parser with subparsers for each category in the categories dict
    given.
    """
    parser = subparsers.add_parser('version')

    parser = subparsers.add_parser('bash-completion')
    parser.add_argument('query_category', nargs='?')

    for category in categories:
        command_object = categories[category]()

        desc = getattr(command_object, 'description', None)
        parser = subparsers.add_parser(category, description=desc)
        parser.set_defaults(command_object=command_object)

        category_subparsers = parser.add_subparsers(dest='action')
        category_subparsers.required = True

        for (action, action_fn) in methods_of(command_object):
            parser = category_subparsers.add_parser(
                action, description=getattr(action_fn, 'description', desc))

            action_kwargs = []
            for args, kwargs in getattr(action_fn, 'args', []):
                # we must handle positional parameters (ARG) separately from
                # positional parameters (--opt). Detect this by checking for
                # the presence of leading '--'
                if args[0] != args[0].lstrip('-'):
                    kwargs.setdefault('dest', args[0].lstrip('-'))
                    if kwargs['dest'].startswith('action_kwarg_'):
                        action_kwargs.append(
                            kwargs['dest'][len('action_kwarg_'):])
                    else:
                        action_kwargs.append(kwargs['dest'])
                        kwargs['dest'] = 'action_kwarg_' + kwargs['dest']
                else:
                    action_kwargs.append(args[0])
                    args = ['action_kwarg_' + arg for arg in args]

                parser.add_argument(*args, **kwargs)

            parser.set_defaults(action_fn=action_fn)
            parser.set_defaults(action_kwargs=action_kwargs)

            parser.add_argument('action_args', nargs='*',
                                help=argparse.SUPPRESS)


def print_bash_completion(categories):
    if not CONF.category.query_category:
        print(" ".join(categories.keys()))
    elif CONF.category.query_category in categories:
        fn = categories[CONF.category.query_category]
        command_object = fn()
        actions = methods_of(command_object)
        print(" ".join([k for (k, v) in actions]))


def get_action_fn():
    fn = CONF.category.action_fn
    fn_args = []
    for arg in CONF.category.action_args:
        if isinstance(arg, six.binary_type):
            arg = arg.decode('utf-8')
        fn_args.append(arg)

    fn_kwargs = {}
    for k in CONF.category.action_kwargs:
        v = getattr(CONF.category, 'action_kwarg_' + k)
        if v is None:
            continue
        if isinstance(v, six.binary_type):
            v = v.decode('utf-8')
        fn_kwargs[k] = v

    # call the action with the remaining arguments
    # check arguments
    missing = validate_args(fn, *fn_args, **fn_kwargs)
    if missing:
        # NOTE(mikal): this isn't the most helpful error message ever. It is
        # long, and tells you a lot of things you probably don't want to know
        # if you just got a single arg wrong.
        print(fn.__doc__)
        CONF.print_help()
        raise exception.Invalid(
            _("Missing arguments: %s") % ", ".join(missing))

    return fn, fn_args, fn_kwargs


def action_description(text):
    """Decorator for adding a description to command action.

    To display help text on action call instead of common category help text
    action function can be decorated.

    command <category> <action> -h will show description and arguments.

    """
    def _decorator(func):
        func.description = text
        return func
    return _decorator
