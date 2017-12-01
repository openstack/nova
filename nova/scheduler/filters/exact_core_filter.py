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

from oslo_log import log as logging

from nova.i18n import _LW
from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class ExactCoreFilter(filters.BaseHostFilter):
    """Exact Core Filter."""

    RUN_ON_REBUILD = False

    def __init__(self, *args, **kwargs):
        super(ExactCoreFilter, self).__init__(*args, **kwargs)
        LOG.warning('ExactCoreFilter is deprecated in Pike and will be '
                    'removed in a subsequent release.')

    def host_passes(self, host_state, spec_obj):
        """Return True if host has the exact number of CPU cores."""
        if not host_state.vcpus_total:
            # Fail safe
            LOG.warning(_LW("VCPUs not set; assuming CPU collection broken"))
            return False

        required_vcpus = spec_obj.vcpus
        usable_vcpus = host_state.vcpus_total - host_state.vcpus_used

        if required_vcpus != usable_vcpus:
            LOG.debug("%(host_state)s does not have exactly "
                      "%(requested_vcpus)s cores of usable vcpu, it has "
                      "%(usable_vcpus)s.",
                      {'host_state': host_state,
                       'requested_vcpus': required_vcpus,
                       'usable_vcpus': usable_vcpus})
            return False

        # NOTE(mgoddard): Setting the limit ensures that it is enforced in
        # compute. This ensures that if multiple instances are scheduled to a
        # single host, then all after the first will fail in the claim.
        host_state.limits['vcpu'] = host_state.vcpus_total
        return True
