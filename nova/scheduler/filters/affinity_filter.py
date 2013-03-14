# Copyright 2012, Piston Cloud Computing, Inc.
# Copyright 2012, OpenStack LLC.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import netaddr

from nova.compute import api as compute
from nova.scheduler import filters


class AffinityFilter(filters.BaseHostFilter):
    def __init__(self):
        self.compute_api = compute.API()


class DifferentHostFilter(AffinityFilter):
    '''Schedule the instance on a different host from a set of instances.'''

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('different_host', [])
        if isinstance(affinity_uuids, basestring):
            affinity_uuids = [affinity_uuids]
        if affinity_uuids:
            return not self.compute_api.get_all(context,
                                                {'host': host_state.host,
                                                 'uuid': affinity_uuids,
                                                 'deleted': False})
        # With no different_host key
        return True


class SameHostFilter(AffinityFilter):
    '''Schedule the instance on the same host as another instance in a set of
    of instances.
    '''

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('same_host', [])
        if isinstance(affinity_uuids, basestring):
            affinity_uuids = [affinity_uuids]
        if affinity_uuids:
            return self.compute_api.get_all(context, {'host': host_state.host,
                                                      'uuid': affinity_uuids,
                                                      'deleted': False})
        # With no same_host key
        return True


class SimpleCIDRAffinityFilter(AffinityFilter):
    def host_passes(self, host_state, filter_properties):
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_cidr = scheduler_hints.get('cidr', '/24')
        affinity_host_addr = scheduler_hints.get('build_near_host_ip')
        host_ip = host_state.capabilities.get('host_ip')
        if affinity_host_addr:
            affinity_net = netaddr.IPNetwork(str.join('', (affinity_host_addr,
                                                           affinity_cidr)))

            return netaddr.IPAddress(host_ip) in affinity_net

        # We don't have an affinity host address.
        return True
