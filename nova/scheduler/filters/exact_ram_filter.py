# Copyright (c) 2014 OpenStack Foundation
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

from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class ExactRamFilter(filters.BaseHostFilter):
    """Exact RAM Filter."""

    RUN_ON_REBUILD = False

    def __init__(self, *args, **kwargs):
        super(ExactRamFilter, self).__init__(*args, **kwargs)
        LOG.warning('ExactRamFilter is deprecated in Pike and will be '
                    'removed in a subsequent release.')

    def host_passes(self, host_state, spec_obj):
        """Return True if host has the exact amount of RAM available."""
        requested_ram = spec_obj.memory_mb
        if requested_ram != host_state.free_ram_mb:
            LOG.debug("%(host_state)s does not have exactly "
                      "%(requested_ram)s MB usable RAM, it has "
                      "%(usable_ram)s MB.",
                      {'host_state': host_state,
                       'requested_ram': requested_ram,
                       'usable_ram': host_state.free_ram_mb})
            return False

        # NOTE(mgoddard): Setting the limit ensures that it is enforced in
        # compute. This ensures that if multiple instances are scheduled to a
        # single host, then all after the first will fail in the claim.
        host_state.limits['memory_mb'] = host_state.total_usable_ram_mb
        return True
