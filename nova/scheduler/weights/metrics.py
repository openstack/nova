# Copyright (c) 2011 OpenStack Foundation
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

"""
Metrics Weigher.  Weigh hosts by their metrics.

This weigher can compute the weight based on the compute node host's various
metrics. The to-be weighed metrics and their weighing ratio are specified
in the configuration file as the followings:

    [metrics]
    weight_setting = name1=1.0, name2=-1.0

    The final weight would be name1.value * 1.0 + name2.value * -1.0.
"""

import nova.conf
from nova import exception
from nova.scheduler import utils
from nova.scheduler import weights


CONF = nova.conf.CONF


class MetricsWeigher(weights.BaseHostWeigher):
    def __init__(self):
        self._parse_setting()

    def _parse_setting(self):
        self.setting = utils.parse_options(CONF.metrics.weight_setting,
                                           sep='=',
                                           converter=float,
                                           name="metrics.weight_setting")

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'metrics_weight_multiplier',
            CONF.metrics.weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        value = 0.0

        # NOTE(sbauza): Keying a dict of Metrics per metric name given that we
        # have a MonitorMetricList object
        metrics_dict = {m.name: m for m in host_state.metrics or []}
        for (name, ratio) in self.setting:
            try:
                value += metrics_dict[name].value * ratio
            except KeyError:
                if CONF.metrics.required:
                    raise exception.ComputeHostMetricNotFound(
                            host=host_state.host,
                            node=host_state.nodename,
                            name=name)
                else:
                    # We treat the unavailable metric as the most negative
                    # factor, i.e. set the value to make this obj would be
                    # at the end of the ordered weighed obj list
                    # Do nothing if ratio or weight_multiplier is 0.
                    if ratio * self.weight_multiplier(host_state) != 0:
                        return CONF.metrics.weight_of_unavailable

        return value
