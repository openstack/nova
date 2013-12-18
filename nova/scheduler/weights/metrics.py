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

from oslo.config import cfg

from nova import exception
from nova.scheduler import utils
from nova.scheduler import weights

metrics_weight_opts = [
        cfg.FloatOpt('weight_multiplier',
                     default=1.0,
                     help='Multiplier used for weighing metrics.'),
        cfg.ListOpt('weight_setting',
                    default=[],
                    help='How the metrics are going to be weighed. This '
                         'should be in the form of "<name1>=<ratio1>, '
                         '<name2>=<ratio2>, ...", where <nameX> is one '
                         'of the metrics to be weighed, and <ratioX> is '
                         'the corresponding ratio. So for "name1=1.0, '
                         'name2=-1.0" The final weight would be '
                         'name1.value * 1.0 + name2.value * -1.0.'),
       cfg.BoolOpt('required',
                    default=True,
                    help='How to treat the unavailable metrics. When a '
                         'metric is NOT available for a host, if it is set '
                         'to be True, it would raise an exception, so it '
                         'is recommended to use the scheduler filter '
                         'MetricFilter to filter out those hosts. If it is '
                         'set to be False, the unavailable metric would be '
                         'treated as a negative factor in weighing '
                         'process, the returned value would be set by '
                         'the option weight_of_unavailable.'),
       cfg.FloatOpt('weight_of_unavailable',
                     default=float(-10000.0),
                     help='The final weight value to be returned if '
                          'required is set to False and any one of the '
                          'metrics set by weight_setting is unavailable.'),
]

CONF = cfg.CONF
CONF.register_opts(metrics_weight_opts, group='metrics')


class MetricsWeigher(weights.BaseHostWeigher):
    def __init__(self):
        self._parse_setting()

    def _parse_setting(self):
        self.setting = utils.parse_options(CONF.metrics.weight_setting,
                                           sep='=',
                                           converter=float,
                                           name="metrics.weight_setting")

    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.metrics.weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        value = 0.0

        for (name, ratio) in self.setting:
            try:
                value += host_state.metrics[name].value * ratio
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
                    if ratio * self.weight_multiplier() != 0:
                        return CONF.metrics.weight_of_unavailable

        return value
