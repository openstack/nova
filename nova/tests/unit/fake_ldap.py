# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""Fake LDAP server for test harness.

This class does very little error checking, and knows nothing about ldap
class definitions.  It implements the minimum emulation of the python ldap
library to work with nova.

"""

import fnmatch

from oslo_serialization import jsonutils
from six.moves import range


class Store(object):
    def __init__(self):
        if hasattr(self.__class__, '_instance'):
            raise Exception('Attempted to instantiate singleton')

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = _StorageDict()
        return cls._instance


class _StorageDict(dict):
    def keys(self, pat=None):
        ret = super(_StorageDict, self).keys()
        if pat is not None:
            ret = fnmatch.filter(ret, pat)
        return ret

    def delete(self, key):
        try:
            del self[key]
        except KeyError:
            pass

    def flushdb(self):
        self.clear()

    def hgetall(self, key):
        """Returns the hash for the given key

        Creates the hash if the key doesn't exist.
        """
        try:
            return self[key]
        except KeyError:
            self[key] = {}
            return self[key]

    def hget(self, key, field):
        hashdict = self.hgetall(key)
        try:
            return hashdict[field]
        except KeyError:
            hashdict[field] = {}
            return hashdict[field]

    def hset(self, key, field, val):
        hashdict = self.hgetall(key)
        hashdict[field] = val

    def hmset(self, key, value_dict):
        hashdict = self.hgetall(key)
        for field, val in value_dict.items():
            hashdict[field] = val


SCOPE_BASE = 0
SCOPE_ONELEVEL = 1  # Not implemented
SCOPE_SUBTREE = 2
MOD_ADD = 0
MOD_DELETE = 1
MOD_REPLACE = 2


class NO_SUCH_OBJECT(Exception):
    """Duplicate exception class from real LDAP module."""
    pass


class OBJECT_CLASS_VIOLATION(Exception):
    """Duplicate exception class from real LDAP module."""
    pass


class SERVER_DOWN(Exception):
    """Duplicate exception class from real LDAP module."""
    pass


def initialize(_uri):
    """Opens a fake connection with an LDAP server."""
    return FakeLDAP()


def _match_query(query, attrs):
    """Match an ldap query to an attribute dictionary.

    The characters &, |, and ! are supported in the query. No syntax checking
    is performed, so malformed queries will not work correctly.
    """
    # cut off the parentheses
    inner = query[1:-1]
    if inner.startswith('&'):
        # cut off the &
        l, r = _paren_groups(inner[1:])
        return _match_query(l, attrs) and _match_query(r, attrs)
    if inner.startswith('|'):
        # cut off the |
        l, r = _paren_groups(inner[1:])
        return _match_query(l, attrs) or _match_query(r, attrs)
    if inner.startswith('!'):
        # cut off the ! and the nested parentheses
        return not _match_query(query[2:-1], attrs)

    (k, _sep, v) = inner.partition('=')
    return _match(k, v, attrs)


def _paren_groups(source):
    """Split a string into parenthesized groups."""
    count = 0
    start = 0
    result = []
    for pos in range(len(source)):
        if source[pos] == '(':
            if count == 0:
                start = pos
            count += 1
        if source[pos] == ')':
            count -= 1
            if count == 0:
                result.append(source[start:pos + 1])
    return result


def _match(key, value, attrs):
    """Match a given key and value against an attribute list."""
    if key not in attrs:
        return False
    # This is a wild card search. Implemented as all or nothing for now.
    if value == "*":
        return True
    if key != "objectclass":
        return value in attrs[key]
    # it is an objectclass check, so check subclasses
    values = _subs(value)
    for v in values:
        if v in attrs[key]:
            return True
    return False


def _subs(value):
    """Returns a list of subclass strings.

    The strings represent the ldap object class plus any subclasses that
    inherit from it. Fakeldap doesn't know about the ldap object structure,
    so subclasses need to be defined manually in the dictionary below.

    """
    subs = {'groupOfNames': ['novaProject']}
    if value in subs:
        return [value] + subs[value]
    return [value]


def _from_json(encoded):
    """Convert attribute values from json representation.

    Args:
    encoded -- a json encoded string

    Returns a list of strings

    """
    return [str(x) for x in jsonutils.loads(encoded)]


def _to_json(unencoded):
    """Convert attribute values into json representation.

    Args:
    unencoded -- an unencoded string or list of strings.  If it
        is a single string, it will be converted into a list.

    Returns a json string

    """
    return jsonutils.dumps(list(unencoded))


server_fail = False


class FakeLDAP(object):
    """Fake LDAP connection."""

    def simple_bind_s(self, dn, password):
        """This method is ignored, but provided for compatibility."""
        if server_fail:
            raise SERVER_DOWN()
        pass

    def unbind_s(self):
        """This method is ignored, but provided for compatibility."""
        if server_fail:
            raise SERVER_DOWN()
        pass

    def add_s(self, dn, attr):
        """Add an object with the specified attributes at dn."""
        if server_fail:
            raise SERVER_DOWN()

        key = "%s%s" % (self.__prefix, dn)
        value_dict = {k: _to_json(v) for k, v in attr}
        Store.instance().hmset(key, value_dict)

    def delete_s(self, dn):
        """Remove the ldap object at specified dn."""
        if server_fail:
            raise SERVER_DOWN()

        Store.instance().delete("%s%s" % (self.__prefix, dn))

    def modify_s(self, dn, attrs):
        """Modify the object at dn using the attribute list.

        :param dn: a dn
        :param attrs: a list of tuples in the following form::

            ([MOD_ADD | MOD_DELETE | MOD_REPACE], attribute, value)

        """
        if server_fail:
            raise SERVER_DOWN()

        store = Store.instance()
        key = "%s%s" % (self.__prefix, dn)

        for cmd, k, v in attrs:
            values = _from_json(store.hget(key, k))
            if cmd == MOD_ADD:
                values.append(v)
            elif cmd == MOD_REPLACE:
                values = [v]
            else:
                values.remove(v)
            store.hset(key, k, _to_json(values))

    def modrdn_s(self, dn, newrdn):
        oldobj = self.search_s(dn, SCOPE_BASE)
        if not oldobj:
            raise NO_SUCH_OBJECT()
        newdn = "%s,%s" % (newrdn, dn.partition(',')[2])
        newattrs = oldobj[0][1]

        modlist = []
        for attrtype in newattrs.keys():
            modlist.append((attrtype, newattrs[attrtype]))

        self.add_s(newdn, modlist)
        self.delete_s(dn)

    def search_s(self, dn, scope, query=None, fields=None):
        """Search for all matching objects under dn using the query.

        Args:
        dn -- dn to search under
        scope -- only SCOPE_BASE and SCOPE_SUBTREE are supported
        query -- query to filter objects by
        fields -- fields to return. Returns all fields if not specified

        """
        if server_fail:
            raise SERVER_DOWN()

        if scope != SCOPE_BASE and scope != SCOPE_SUBTREE:
            raise NotImplementedError(str(scope))
        store = Store.instance()
        if scope == SCOPE_BASE:
            pattern = "%s%s" % (self.__prefix, dn)
            keys = store.keys(pattern)
        else:
            keys = store.keys("%s*%s" % (self.__prefix, dn))

        if not keys:
            raise NO_SUCH_OBJECT()

        objects = []
        for key in keys:
            # get the attributes from the store
            attrs = store.hgetall(key)
            # turn the values from the store into lists
            attrs = {k: _from_json(v) for k, v in attrs.items()}
            # filter the objects by query
            if not query or _match_query(query, attrs):
                # filter the attributes by fields
                attrs = {k: v for k, v in attrs.items()
                         if not fields or k in fields}
                objects.append((key[len(self.__prefix):], attrs))
        return objects

    @property
    def __prefix(self):
        """Get the prefix to use for all keys."""
        return 'ldap:'
