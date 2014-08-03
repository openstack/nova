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

from nova.openstack.common import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)


class ExactDiskFilter(filters.BaseHostFilter):
    """Exact Disk Filter."""

    def host_passes(self, host_state, filter_properties):
        """Return True if host has the exact amount of disk available."""
        instance_type = filter_properties.get('instance_type')
        requested_disk = (1024 * (instance_type['root_gb'] +
                                  instance_type['ephemeral_gb']) +
                          instance_type['swap'])

        if requested_disk != host_state.free_disk_mb:
            LOG.debug("%(host_state)s does not have exactly "
                      "%(requested_disk)s MB usable disk, it "
                      "has %(usable_disk_mb)s.",
                      {'host_state': host_state,
                       'requested_disk': requested_disk,
                       'usable_disk_mb': host_state.free_disk_mb})
            return False

        return True
