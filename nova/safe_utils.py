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

    This method can only properly grab arguments which are passed in as
    keyword arguments, or given names by the method being called.  This means
    that an ``*arg`` in a method signature and any arguments captured by it
    will be left out of the results.

    As an example: if function is defined as function(red, blue, green, *args)
    then arguments captured by *args won't be returned.  If function is called
    as function('red', 'blue', 'green') those will all be captured.
    """
    keyed_args = {}
    argnames, varargs, keywords, defaults = inspect.getargspec(function)

    keyed_args.update(kwargs)

    remaining_argnames = filter(lambda x: x not in keyed_args, argnames)
    keyed_args.update(dict(zip(remaining_argnames, args)))

    if defaults:
        num_defaults = len(defaults)
        for argname, value in zip(argnames[-num_defaults:], defaults):
            if argname not in keyed_args:
                keyed_args[argname] = value

    return keyed_args
