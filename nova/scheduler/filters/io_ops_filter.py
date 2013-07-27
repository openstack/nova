# Copyright (c) 2012 OpenStack Foundation
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

from oslo.config import cfg

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.scheduler import filters

LOG = logging.getLogger(__name__)

max_io_ops_per_host_opt = cfg.IntOpt("max_io_ops_per_host",
        default=8,
        help="Ignore hosts that have too many builds/resizes/snaps/migrations")

CONF = cfg.CONF
CONF.register_opt(max_io_ops_per_host_opt)


class IoOpsFilter(filters.BaseHostFilter):
    """Filter out hosts with too many concurrent I/O operations."""

    def host_passes(self, host_state, filter_properties):
        """Use information about current vm and task states collected from
        compute node statistics to decide whether to filter.
        """
        num_io_ops = host_state.num_io_ops
        max_io_ops = CONF.max_io_ops_per_host
        passes = num_io_ops < max_io_ops
        if not passes:
            LOG.debug(_("%(host_state)s fails I/O ops check: Max IOs per host "
                        "is set to %(max_io_ops)s"),
                        {'host_state': host_state,
                         'max_io_ops': max_io_ops})
        return passes
