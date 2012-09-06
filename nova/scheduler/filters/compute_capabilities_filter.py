# Copyright (c) 2011 OpenStack, LLC.
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

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler.filters import extra_specs_ops


LOG = logging.getLogger(__name__)


class ComputeCapabilitiesFilter(filters.BaseHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""

    def _satisfies_extra_specs(self, capabilities, instance_type):
        """Check that the capabilities provided by the compute service
        satisfy the extra specs associated with the instance type"""
        if 'extra_specs' not in instance_type:
            return True

        for key, req in instance_type['extra_specs'].iteritems():
            # NOTE(jogo) any key containing a scope (scope is terminated
            # by a `:') will be ignored by this filter. (bug 1039386)
            if key.count(':'):
                continue
            cap = capabilities.get(key, None)
            if not extra_specs_ops.match(cap, req):
                return False
        return True

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type."""
        instance_type = filter_properties.get('instance_type')
        if not self._satisfies_extra_specs(host_state.capabilities,
                instance_type):
            LOG.debug(_("%(host_state)s fails instance_type extra_specs "
                    "requirements"), locals())
            return False
        return True
