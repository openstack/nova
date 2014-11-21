# Copyright 2012, Piston Cloud Computing, Inc.
# Copyright 2012, OpenStack Foundation
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
import six

from nova.compute import api as compute
from nova.openstack.common import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class AffinityFilter(filters.BaseHostFilter):
    def __init__(self):
        self.compute_api = compute.API()


class DifferentHostFilter(AffinityFilter):
    '''Schedule the instance on a different host from a set of instances.'''

    # The hosts the instances are running on doesn't change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('different_host', [])
        if isinstance(affinity_uuids, six.string_types):
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
    instances.
    '''

    # The hosts the instances are running on doesn't change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        context = filter_properties['context']
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_uuids = scheduler_hints.get('same_host', [])
        if isinstance(affinity_uuids, six.string_types):
            affinity_uuids = [affinity_uuids]
        if affinity_uuids:
            return self.compute_api.get_all(context, {'host': host_state.host,
                                                      'uuid': affinity_uuids,
                                                      'deleted': False})
        # With no same_host key
        return True


class SimpleCIDRAffinityFilter(AffinityFilter):
    '''Schedule the instance on a host with a particular cidr
    '''

    # The address of a host doesn't change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        affinity_cidr = scheduler_hints.get('cidr', '/24')
        affinity_host_addr = scheduler_hints.get('build_near_host_ip')
        host_ip = host_state.host_ip
        if affinity_host_addr:
            affinity_net = netaddr.IPNetwork(str.join('', (affinity_host_addr,
                                                           affinity_cidr)))

            return netaddr.IPAddress(host_ip) in affinity_net

        # We don't have an affinity host address.
        return True


class _GroupAntiAffinityFilter(AffinityFilter):
    """Schedule the instance on a different host from a set of group
    hosts.
    """

    def __init__(self):
        super(_GroupAntiAffinityFilter, self).__init__()

    def host_passes(self, host_state, filter_properties):
        # Only invoke the filter is 'anti-affinity' is configured
        policies = filter_properties.get('group_policies', [])
        if self.policy_name not in policies:
            return True

        group_hosts = filter_properties.get('group_hosts') or []
        LOG.debug("Group anti affinity: check if %(host)s not "
                    "in %(configured)s", {'host': host_state.host,
                                           'configured': group_hosts})
        if group_hosts:
            return host_state.host not in group_hosts

        # No groups configured
        return True


class ServerGroupAntiAffinityFilter(_GroupAntiAffinityFilter):
    def __init__(self):
        self.policy_name = 'anti-affinity'
        super(ServerGroupAntiAffinityFilter, self).__init__()


class _GroupAffinityFilter(AffinityFilter):
    """Schedule the instance on to host from a set of group hosts.
    """

    def __init__(self):
        super(_GroupAffinityFilter, self).__init__()

    def host_passes(self, host_state, filter_properties):
        # Only invoke the filter is 'affinity' is configured
        policies = filter_properties.get('group_policies', [])
        if self.policy_name not in policies:
            return True

        group_hosts = filter_properties.get('group_hosts', [])
        LOG.debug("Group affinity: check if %(host)s in "
                    "%(configured)s", {'host': host_state.host,
                                        'configured': group_hosts})
        if group_hosts:
            return host_state.host in group_hosts

        # No groups configured
        return True


class ServerGroupAffinityFilter(_GroupAffinityFilter):
    def __init__(self):
        self.policy_name = 'affinity'
        super(ServerGroupAffinityFilter, self).__init__()
