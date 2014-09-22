# Copyright (c) 2014 OpenStack Foundation
#
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


from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class ExactCoreFilter(filters.BaseHostFilter):
    """Exact Core Filter."""

    def host_passes(self, host_state, filter_properties):
        """Return True if host has the exact number of CPU cores."""
        instance_type = filter_properties.get('instance_type')
        if not instance_type:
            return True

        if not host_state.vcpus_total:
            # Fail safe
            LOG.warning(_LW("VCPUs not set; assuming CPU collection broken"))
            return False

        required_vcpus = instance_type['vcpus']
        usable_vcpus = host_state.vcpus_total - host_state.vcpus_used

        if required_vcpus != usable_vcpus:
            LOG.debug("%(host_state)s does not have exactly "
                      "%(requested_vcpus)s cores of usable vcpu, it has "
                      "%(usable_vcpus)s.",
                      {'host_state': host_state,
                       'requested_vcpus': required_vcpus,
                       'usable_vcpus': usable_vcpus})
            return False

        return True
