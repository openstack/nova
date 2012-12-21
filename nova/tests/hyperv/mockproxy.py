# vim: tabstop=4 shiftwidth=4 softtabstop=4

#  Copyright 2012 Cloudbase Solutions Srl
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

"""
Classes for dynamic generation of mock objects.
"""

import inspect


def serialize_obj(obj):
    if isinstance(obj, float):
        val = str(round(obj, 10))
    elif isinstance(obj, dict):
        d = {}
        for k1, v1 in obj.items():
            d[k1] = serialize_obj(v1)
        val = str(d)
    elif isinstance(obj, list):
        l1 = []
        for i1 in obj:
            l1.append(serialize_obj(i1))
        val = str(l1)
    elif isinstance(obj, tuple):
        l1 = ()
        for i1 in obj:
            l1 = l1 + (serialize_obj(i1),)
        val = str(l1)
    else:
        if isinstance(obj, str) or isinstance(obj, unicode):
            val = obj
        elif hasattr(obj, '__str__') and inspect.ismethod(obj.__str__):
            val = str(obj)
        else:
            val = str(type(obj))
    return val


def serialize_args(*args, **kwargs):
    """Workaround for float string conversion issues in Python 2.6"""
    return serialize_obj((args, kwargs))


class MockException(Exception):
    def __init__(self, message):
        super(MockException, self).__init__(message)


class Mock(object):
    def _get_next_value(self, name):
        c = self._access_count.get(name)
        if c is None:
            c = 0
        else:
            c = c + 1
        self._access_count[name] = c

        try:
            value = self._values[name][c]
        except IndexError as ex:
            raise MockException(_('Couldn\'t find invocation num. %(c)d '
                'of attribute "%(name)s"') % locals())
        return value

    def _get_next_ret_value(self, name, params):
        d = self._access_count.get(name)
        if d is None:
            d = {}
            self._access_count[name] = d
        c = d.get(params)
        if c is None:
            c = 0
        else:
            c = c + 1
        d[params] = c

        try:
            m = self._values[name]
        except KeyError as ex:
            raise MockException(_('Couldn\'t find attribute "%s"') % (name))

        try:
            value = m[params][c]
        except KeyError as ex:
            raise MockException(_('Couldn\'t find attribute "%(name)s" '
                'with arguments "%(params)s"') % locals())
        except IndexError as ex:
            raise MockException(_('Couldn\'t find invocation num. %(c)d '
                'of attribute "%(name)s" with arguments "%(params)s"')
                    % locals())

        return value

    def __init__(self, values):
        self._values = values
        self._access_count = {}

    def has_values(self):
        return len(self._values) > 0

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            return object.__getattribute__(self, name)
        else:
            try:
                isdict = isinstance(self._values[name], dict)
            except KeyError as ex:
                raise MockException(_('Couldn\'t find attribute "%s"')
                    % (name))

            if isdict:
                def newfunc(*args, **kwargs):
                    params = serialize_args(args, kwargs)
                    return self._get_next_ret_value(name, params)
                return newfunc
            else:
                return self._get_next_value(name)

    def __str__(self):
        return self._get_next_value('__str__')

    def __iter__(self):
        return getattr(self._get_next_value('__iter__'), '__iter__')()

    def __len__(self):
        return self._get_next_value('__len__')

    def __getitem__(self, key):
        return self._get_next_ret_value('__getitem__', str(key))

    def __call__(self, *args, **kwargs):
        params = serialize_args(args, kwargs)
        return self._get_next_ret_value('__call__', params)


class MockProxy(object):
    def __init__(self, wrapped):
        self._wrapped = wrapped
        self._recorded_values = {}

    def _get_proxy_object(self, obj):
        if hasattr(obj, '__dict__') or isinstance(obj, tuple) or \
            isinstance(obj, list) or isinstance(obj, dict):
            p = MockProxy(obj)
        else:
            p = obj
        return p

    def __getattr__(self, name):
        if name in ['_wrapped']:
            return object.__getattribute__(self, name)
        else:
            attr = getattr(self._wrapped, name)
            if inspect.isfunction(attr) or inspect.ismethod(attr) or \
                inspect.isbuiltin(attr):
                def newfunc(*args, **kwargs):
                    result = attr(*args, **kwargs)
                    p = self._get_proxy_object(result)
                    params = serialize_args(args, kwargs)
                    self._add_recorded_ret_value(name, params, p)
                    return p
                return newfunc
            elif hasattr(attr, '__dict__') or (hasattr(attr, '__getitem__')
                and not (isinstance(attr, str) or isinstance(attr, unicode))):
                p = MockProxy(attr)
            else:
                p = attr
            self._add_recorded_value(name, p)
            return p

    def __setattr__(self, name, value):
        if name in ['_wrapped', '_recorded_values']:
            object.__setattr__(self, name, value)
        else:
            setattr(self._wrapped, name, value)

    def _add_recorded_ret_value(self, name, params, val):
        d = self._recorded_values.get(name)
        if d is None:
            d = {}
            self._recorded_values[name] = d
        l = d.get(params)
        if l is None:
            l = []
            d[params] = l
        l.append(val)

    def _add_recorded_value(self, name, val):
        if not name in self._recorded_values:
            self._recorded_values[name] = []
        self._recorded_values[name].append(val)

    def get_mock(self):
        values = {}
        for k, v in self._recorded_values.items():
            if isinstance(v, dict):
                d = {}
                values[k] = d
                for k1, v1 in v.items():
                    l = []
                    d[k1] = l
                    for i1 in v1:
                        if isinstance(i1, MockProxy):
                            l.append(i1.get_mock())
                        else:
                            l.append(i1)
            else:
                l = []
                values[k] = l
                for i in v:
                    if isinstance(i, MockProxy):
                        l.append(i.get_mock())
                    elif isinstance(i, dict):
                        d = {}
                        for k1, v1 in v.items():
                            if isinstance(v1, MockProxy):
                                d[k1] = v1.get_mock()
                            else:
                                d[k1] = v1
                        l.append(d)
                    elif isinstance(i, list):
                        l1 = []
                        for i1 in i:
                            if isinstance(i1, MockProxy):
                                l1.append(i1.get_mock())
                            else:
                                l1.append(i1)
                        l.append(l1)
                    else:
                        l.append(i)
        return Mock(values)

    def __str__(self):
        s = str(self._wrapped)
        self._add_recorded_value('__str__', s)
        return s

    def __len__(self):
        l = len(self._wrapped)
        self._add_recorded_value('__len__', l)
        return l

    def __iter__(self):
        it = []
        for i in self._wrapped:
            it.append(self._get_proxy_object(i))
        self._add_recorded_value('__iter__', it)
        return iter(it)

    def __getitem__(self, key):
        p = self._get_proxy_object(self._wrapped[key])
        self._add_recorded_ret_value('__getitem__', str(key), p)
        return p

    def __call__(self, *args, **kwargs):
        c = self._wrapped(*args, **kwargs)
        p = self._get_proxy_object(c)
        params = serialize_args(args, kwargs)
        self._add_recorded_ret_value('__call__', params, p)
        return p
