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

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler import utils

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('weight_setting',
                'nova.scheduler.weights.metrics',
                group='metrics')


class MetricsFilter(filters.BaseHostFilter):
    """Metrics Filter

    This filter is used to filter out those hosts which don't have the
    corresponding metrics so these the metrics weigher won't fail due to
    these hosts.
    """

    def __init__(self):
        super(MetricsFilter, self).__init__()
        opts = utils.parse_options(CONF.metrics.weight_setting,
                                   sep='=',
                                   converter=float,
                                   name="metrics.weight_setting")
        self.keys = [x[0] for x in opts]

    def host_passes(self, host_state, filter_properties):
        unavail = [i for i in self.keys if i not in host_state.metrics]
        if unavail:
            LOG.debug("%(host_state)s does not have the following "
                        "metrics: %(metrics)s",
                      {'host_state': host_state,
                       'metrics': ', '.join(unavail)})
        return len(unavail) == 0
