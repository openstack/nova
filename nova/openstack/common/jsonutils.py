# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

'''
JSON related utilities.

This module provides a few things:

    1) A handy function for getting an object down to something that can be
    JSON serialized.  See to_primitive().

    2) Wrappers around loads() and dumps().  The dumps() wrapper will
    automatically use to_primitive() for you if needed.

    3) This sets up anyjson to use the loads() and dumps() wrappers if anyjson
    is available.
'''


import datetime
import inspect
import itertools
import json
import xmlrpclib


def to_primitive(value, convert_instances=False, level=0):
    """Convert a complex object into primitives.

    Handy for JSON serialization. We can optionally handle instances,
    but since this is a recursive function, we could have cyclical
    data structures.

    To handle cyclical data structures we could track the actual objects
    visited in a set, but not all objects are hashable. Instead we just
    track the depth of the object inspections and don't go too deep.

    Therefore, convert_instances=True is lossy ... be aware.

    """
    nasty = [inspect.ismodule, inspect.isclass, inspect.ismethod,
             inspect.isfunction, inspect.isgeneratorfunction,
             inspect.isgenerator, inspect.istraceback, inspect.isframe,
             inspect.iscode, inspect.isbuiltin, inspect.isroutine,
             inspect.isabstract]
    for test in nasty:
        if test(value):
            return unicode(value)

    # value of itertools.count doesn't get caught by inspects
    # above and results in infinite loop when list(value) is called.
    if type(value) == itertools.count:
        return unicode(value)

    # FIXME(vish): Workaround for LP bug 852095. Without this workaround,
    #              tests that raise an exception in a mocked method that
    #              has a @wrap_exception with a notifier will fail. If
    #              we up the dependency to 0.5.4 (when it is released) we
    #              can remove this workaround.
    if getattr(value, '__module__', None) == 'mox':
        return 'mock'

    if level > 3:
        return '?'

    # The try block may not be necessary after the class check above,
    # but just in case ...
    try:
        # It's not clear why xmlrpclib created their own DateTime type, but
        # for our purposes, make it a datetime type which is explicitly
        # handled
        if isinstance(value, xmlrpclib.DateTime):
            value = datetime.datetime(*tuple(value.timetuple())[:6])

        if isinstance(value, (list, tuple)):
            o = []
            for v in value:
                o.append(to_primitive(v, convert_instances=convert_instances,
                                      level=level))
            return o
        elif isinstance(value, dict):
            o = {}
            for k, v in value.iteritems():
                o[k] = to_primitive(v, convert_instances=convert_instances,
                                    level=level)
            return o
        elif isinstance(value, datetime.datetime):
            return str(value)
        elif hasattr(value, 'iteritems'):
            return to_primitive(dict(value.iteritems()),
                                convert_instances=convert_instances,
                                level=level)
        elif hasattr(value, '__iter__'):
            return to_primitive(list(value), level)
        elif convert_instances and hasattr(value, '__dict__'):
            # Likely an instance of something. Watch for cycles.
            # Ignore class member vars.
            return to_primitive(value.__dict__,
                                convert_instances=convert_instances,
                                level=level + 1)
        else:
            return value
    except TypeError, e:
        # Class objects are tricky since they may define something like
        # __iter__ defined but it isn't callable as list().
        return unicode(value)


def dumps(value, default=to_primitive, **kwargs):
    return json.dumps(value, default=default, **kwargs)


def loads(s):
    return json.loads(s)


try:
    import anyjson
except ImportError:
    pass
else:
    anyjson._modules.append((__name__, 'dumps', TypeError,
                                       'loads', ValueError))
    anyjson.force_implementation(__name__)
