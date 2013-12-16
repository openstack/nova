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

    metrics_weight_setting = name1=1.0, name2=-1.0

    The final weight would be name1.value * 1.0 + name2.value * -1.0.
"""

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
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
                         'of the metric to be weighed, and <ratioX> is '
                         'the corresponding ratio. So for "name1=1.0, '
                         'name2=-1.0" The final weight would be '
                         'name1.value * 1.0 + name2.value * -1.0.'),
]

CONF = cfg.CONF
CONF.register_opts(metrics_weight_opts, group='metrics')

LOG = logging.getLogger(__name__)


class MetricsWeigher(weights.BaseHostWeigher):
    def __init__(self):
        self._parse_setting()

    def _parse_setting(self):
        self.setting = []
        bad = []
        for item in CONF.metrics.weight_setting:
            try:
                (name, ratio) = item.split('=')
                ratio = float(ratio)
            except ValueError:
                name = None
                ratio = None
            if name and ratio is not None:
                self.setting.append((name, ratio))
            else:
                bad.append(item)
        if bad:
            LOG.error(_("Ignoring the invalid elements of"
                        " metrics_weight_setting: %s"),
                      ",".join(bad))

    def weight_multiplier(self):
        """Override the weight multiplier."""
        return CONF.metrics.weight_multiplier

    def _weigh_object(self, host_state, weight_properties):
        value = 0.0

        for (name, ratio) in self.setting:
            try:
                value += host_state.metrics[name].value * ratio
            except KeyError:
                raise exception.ComputeHostMetricNotFound(
                        host=host_state.host,
                        node=host_state.nodename,
                        name=name)
        return value
