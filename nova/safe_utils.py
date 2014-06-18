# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

"""Utilities and helper functions that won't produce circular imports."""

import inspect


def getcallargs(function, *args, **kwargs):
    """This is a simplified inspect.getcallargs (2.7+).

    It should be replaced when python >= 2.7 is standard.
    """
    keyed_args = {}
    argnames, varargs, keywords, defaults = inspect.getargspec(function)

    keyed_args.update(kwargs)

    # NOTE(alaski) the implicit 'self' or 'cls' argument shows up in
    # argnames but not in args or kwargs.  Uses 'in' rather than '==' because
    # some tests use 'self2'.
    if 'self' in argnames[0] or 'cls' == argnames[0]:
        # The function may not actually be a method or have im_self.
        # Typically seen when it's stubbed with mox.
        if inspect.ismethod(function) and hasattr(function, 'im_self'):
            keyed_args[argnames[0]] = function.im_self
        else:
            keyed_args[argnames[0]] = None

    remaining_argnames = filter(lambda x: x not in keyed_args, argnames)
    keyed_args.update(dict(zip(remaining_argnames, args)))

    if defaults:
        num_defaults = len(defaults)
        for argname, value in zip(argnames[-num_defaults:], defaults):
            if argname not in keyed_args:
                keyed_args[argname] = value

    return keyed_args
