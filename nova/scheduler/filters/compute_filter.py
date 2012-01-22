# Copyright (c) 2011 Openstack, LLC.
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

from nova import log as logging
from nova.scheduler.filters import abstract_filter
from nova import utils


LOG = logging.getLogger('nova.scheduler.filter.compute_filter')


class ComputeFilter(abstract_filter.AbstractHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""

    def _satisfies_extra_specs(self, capabilities, instance_type):
        """Check that the capabilities provided by the compute service
        satisfy the extra specs associated with the instance type"""
        if 'extra_specs' not in instance_type:
            return True

        # NOTE(lorinh): For now, we are just checking exact matching on the
        # values. Later on, we want to handle numerical
        # values so we can represent things like number of GPU cards
        for key, value in instance_type['extra_specs'].iteritems():
            if capabilities.get(key, None) != value:
                return False
        return True

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type."""
        instance_type = filter_properties.get('instance_type')
        if host_state.topic != 'compute' or not instance_type:
            return True
        capabilities = host_state.capabilities
        service = host_state.service

        if not utils.service_is_up(service) or service['disabled']:
            return False
        if not capabilities.get("enabled", True):
            return False
        if not self._satisfies_extra_specs(capabilities, instance_type):
            return False
        return True
