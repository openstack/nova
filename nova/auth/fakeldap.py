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


class NO_SUCH_OBJECT(Exception):
    pass


def initialize(uri):
    return FakeLDAP(uri)


class FakeLDAP(object):
    def __init__(self, _uri):
        self.keeper = datastore.Keeper('fakeldap')
        if self.keeper['objects'] is None:
            self.keeper['objects'] = {}

    def simple_bind_s(self, dn, password):
        pass

    def unbind_s(self):
        pass

    def search_s(self, dn, scope, query=None, fields=None):
        logging.debug("searching for %s" % dn)
        filtered = {}
        d = self.keeper['objects'] or {}
        for cn, attrs in d.iteritems():
            if cn[-len(dn):] == dn:
                filtered[cn] = attrs
        if query:
            k,v = query[1:-1].split('=')
            objects = {}
            for cn, attrs in filtered.iteritems():
                if attrs.has_key(k) and (v in attrs[k] or
                    v == attrs[k]):
                    objects[cn] = attrs
        if objects == {}:
            raise NO_SUCH_OBJECT()
        return objects.items()

    def add_s(self, cn, attr):
        logging.debug("adding %s" % cn)
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
        logging.debug("creating for %s" % cn)
        d = self.keeper['objects'] or {}
        del d[cn]
        self.keeper['objects'] = d
