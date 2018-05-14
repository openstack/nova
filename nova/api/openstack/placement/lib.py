# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Symbols intended to be imported by both placement code and placement API
consumers.  When placement is separated out, this module should be part of a
common library that both placement and its consumers can require."""


class RequestGroup(object):
    def __init__(self, use_same_provider=True, resources=None,
                 required_traits=None, forbidden_traits=None, member_of=None):
        """Create a grouping of resource and trait requests.

        :param use_same_provider:
            If True, (the default) this RequestGroup represents requests for
            resources and traits which must be satisfied by a single resource
            provider.  If False, represents a request for resources and traits
            in any resource provider in the same tree, or a sharing provider.
        :param resources: A dict of { resource_class: amount, ... }
        :param required_traits: A set of { trait_name, ... }
        :param forbidden_traits: A set of { trait_name, ... }
        :param member_of: A list of [ [aggregate_UUID],
                                      [aggregate_UUID, aggregate_UUID] ... ]
        """
        self.use_same_provider = use_same_provider
        self.resources = resources or {}
        self.required_traits = required_traits or set()
        self.forbidden_traits = forbidden_traits or set()
        self.member_of = member_of or []

    def __str__(self):
        ret = 'RequestGroup(use_same_provider=%s' % str(self.use_same_provider)
        ret += ', resources={%s}' % ', '.join(
            '%s:%d' % (rc, amount)
            for rc, amount in sorted(list(self.resources.items())))
        ret += ', traits=[%s]' % ', '.join(
            sorted(self.required_traits) +
            ['!%s' % ft for ft in self.forbidden_traits])
        ret += ', aggregates=[%s]' % ', '.join(
            sorted('[%s]' % ', '.join(agglist)
                   for agglist in sorted(self.member_of)))
        ret += ')'
        return ret
