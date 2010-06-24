# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
  Fake LDAP server for test harnesses.
"""

import logging

from nova import datastore

SCOPE_SUBTREE  = 1
MOD_ADD = 0
MOD_DELETE = 1

SUBS = {
    'groupOfNames': ['novaProject']
}


class NO_SUCH_OBJECT(Exception):
    pass


def initialize(uri):
    return FakeLDAP(uri)


class FakeLDAP(object):
    def __init__(self, _uri):
        self.keeper = datastore.SqliteKeeper('fakeldap') #Redis keeper never works here...
        if self.keeper['objects'] is None:
            self.keeper['objects'] = {}

    def simple_bind_s(self, dn, password):
        pass

    def unbind_s(self):
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
        if v in SUBS:
            return [v] + SUBS[v]
        return [v]

    def _match(self, k, v, attrs):
        if attrs.has_key(k):
            for v in self._subs(v):
                if (v in attrs[k]):
                    return True
        return False

    def search_s(self, dn, scope, query=None, fields=None):
        #logging.debug("searching for %s" % dn)
        filtered = {}
        d = self.keeper['objects'] or {}
        for cn, attrs in d.iteritems():
            if cn[-len(dn):] == dn:
                filtered[cn] = attrs
        objects = filtered
        if query:
            objects = {}
            for cn, attrs in filtered.iteritems():
                if self._match_query(query, attrs):
                    objects[cn] = attrs
        if objects == {}:
            raise NO_SUCH_OBJECT()
        return objects.items()

    def add_s(self, cn, attr):
        #logging.debug("adding %s" % cn)
        stored = {}
        for k, v in attr:
            if type(v) is list:
                stored[k] = v
            else:
                stored[k] = [v]
        d = self.keeper['objects']
        d[cn] = stored
        self.keeper['objects'] = d

    def delete_s(self, cn):
        logging.debug("deleting %s" % cn)
        d = self.keeper['objects']
        del d[cn]
        self.keeper['objects'] = d

    def modify_s(self, cn, attr):
        logging.debug("modifying %s" % cn)
        d = self.keeper['objects']
        for cmd, k, v in attr:
            logging.debug("command %s" % cmd)
            if cmd == MOD_ADD:
                d[cn][k].append(v)
            else:
                d[cn][k].remove(v)
        self.keeper['objects'] = d




