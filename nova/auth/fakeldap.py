# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
  Fake LDAP server for test harnesses.
"""

import json

from nova import datastore

SCOPE_SUBTREE  = 2
MOD_ADD = 0
MOD_DELETE = 1


class NO_SUCH_OBJECT(Exception):
    pass


def initialize(uri):
    return FakeLDAP()


class FakeLDAP(object):

    def simple_bind_s(self, dn, password):
        """This method is ignored, but provided for compatibility"""
        pass

    def unbind_s(self):
        """This method is ignored, but provided for compatibility"""
        pass

    def _paren_groups(self, source):
        count = 0
        start = 0
        result = []
        for pos in xrange(len(source)):
            if source[pos] == '(':
                if count == 0:
                    start = pos
                count += 1
            if source[pos] == ')':
                count -= 1
                if count == 0:
                    result.append(source[start:pos+1])
        return result

    def _match_query(self, query, attrs):
        inner = query[1:-1]
        if inner.startswith('&'):
            l, r = self._paren_groups(inner[1:])
            return self._match_query(l, attrs) and self._match_query(r, attrs)
        if inner.startswith('|'):
            l, r = self._paren_groups(inner[1:])
            return self._match_query(l, attrs) or self._match_query(r, attrs)
        if inner.startswith('!'):
            return not self._match_query(query[2:-1], attrs)

        (k, sep, v) = inner.partition('=')
        return self._match(k, v, attrs)

    def _subs(self, v):
        subs = {
            'groupOfNames': ['novaProject']
        }
        if v in subs:
            return [v] + subs[v]
        return [v]

    def _match(self, k, v, attrs):
        if attrs.has_key(k):
            for v in self._subs(v):
                if v in attrs[k]:
                    return True
        return False


    def search_s(self, dn, scope, query=None, fields=None):
        """search for all matching objects under dn using the query
        only SCOPE_SUBTREE is supported.
        """
        if scope != SCOPE_SUBTREE:
            raise NotImplementedError(str(scope))
        redis = datastore.Redis.instance()
        keys = redis.keys(self._redis_prefix + '*' + dn)
        objects = []
        for key in keys:
            # get the attributes from redis
            attrs = redis.hgetall(key)
            # turn the values from redis into lists
            attrs = dict([(k, self._from_json(v))
                          for k, v in attrs.iteritems()])
            # filter the objects by query
            if not query or self._match_query(query, attrs):
                # filter the attributes by fields
                attrs = dict([(k, v) for k, v in attrs.iteritems()
                              if not fields or k in fields])
                objects.append((key[len(self._redis_prefix):], attrs))
        if objects == []:
            raise NO_SUCH_OBJECT()
        return objects

    @property
    def _redis_prefix(self):
        return 'ldap:'

    def _from_json(self, encoded):
        """Convert attribute values from json representation."""
        # return as simple strings instead of unicode strings
        return [str(x) for x in json.loads(encoded)]

    def _to_json(self, unencoded):
        """Convert attribute values into json representation."""
        # all values are returned as lists from ldap
        return json.dumps(list(unencoded))

    def add_s(self, dn, attr):
        """Add an object with the specified attributes at dn."""
        key = self._redis_prefix + dn

        value_dict = dict([(k, self._to_json(v)) for k, v in attr])
        datastore.Redis.instance().hmset(key, value_dict)

    def delete_s(self, dn):
        """Remove the ldap object at specified dn."""
        datastore.Redis.instance().delete(self._redis_prefix + dn)

    def modify_s(self, dn, attrs):
        """Modify the object at dn using the attribute list.
        attr is a list of tuples in the following form:
            ([MOD_ADD | MOD_DELETE], attribute, value)
        """
        redis = datastore.Redis.instance()
        key = self._redis_prefix + dn

        for cmd, k, v in attrs:
            values = self._from_json(redis.hget(key, k))
            if cmd == MOD_ADD:
                values.append(v)
            else:
                values.remove(v)
            values = redis.hset(key, k, self._to_json(values))

