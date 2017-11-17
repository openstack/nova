# Copyright (c) 2014 Intel, Inc.
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

import nova.conf
from nova.scheduler import filters
from nova.scheduler import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class MetricsFilter(filters.BaseHostFilter):
    """Metrics Filter

    This filter is used to filter out those hosts which don't have the
    corresponding metrics so these the metrics weigher won't fail due to
    these hosts.
    """

    RUN_ON_REBUILD = False

    def __init__(self):
        super(MetricsFilter, self).__init__()
        opts = utils.parse_options(CONF.metrics.weight_setting,
                                   sep='=',
                                   converter=float,
                                   name="metrics.weight_setting")
        self.keys = set([x[0] for x in opts])

    def host_passes(self, host_state, spec_obj):
        metrics_on_host = set(m.name for m in host_state.metrics)
        if not self.keys.issubset(metrics_on_host):
            unavail = metrics_on_host - self.keys
            LOG.debug("%(host_state)s does not have the following "
                        "metrics: %(metrics)s",
                      {'host_state': host_state,
                       'metrics': ', '.join(unavail)})
            return False
        return True
