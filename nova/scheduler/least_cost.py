# Copyright (c) 2011 OpenStack, LLC.
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
Least Cost is an algorithm for choosing which host machines to
provision a set of resources to. The input is a WeightedHost object which
is decided upon by a set of objective-functions, called the 'cost-functions'.
The WeightedHost contains a combined weight for each cost-function.

The cost-function and weights are tabulated, and the host with the least cost
is then selected for provisioning.
"""

from nova import config
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)

least_cost_opts = [
    cfg.ListOpt('least_cost_functions',
                default=[
                  'nova.scheduler.least_cost.compute_fill_first_cost_fn'
                  ],
                help='Which cost functions the LeastCostScheduler should use'),
    cfg.FloatOpt('noop_cost_fn_weight',
             default=1.0,
               help='How much weight to give the noop cost function'),
    cfg.FloatOpt('compute_fill_first_cost_fn_weight',
             default=-1.0,
               help='How much weight to give the fill-first cost function. '
                    'A negative value will reverse behavior: '
                    'e.g. spread-first'),
    ]

CONF = config.CONF
CONF.register_opts(least_cost_opts)

# TODO(sirp): Once we have enough of these rules, we can break them out into a
# cost_functions.py file (perhaps in a least_cost_scheduler directory)


class WeightedHost(object):
    """Reduced set of information about a host that has been weighed.
    This is an attempt to remove some of the ad-hoc dict structures
    previously used."""

    def __init__(self, weight, host_state=None):
        self.weight = weight
        self.host_state = host_state

    def to_dict(self):
        x = dict(weight=self.weight)
        if self.host_state:
            x['host'] = self.host_state.host
        return x

    def __repr__(self):
        if self.host_state:
            return "WeightedHost host: %s" % self.host_state.host
        return "WeightedHost with no host_state"


def noop_cost_fn(host_state, weighing_properties):
    """Return a pre-weight cost of 1 for each host"""
    return 1


def compute_fill_first_cost_fn(host_state, weighing_properties):
    """More free ram = higher weight. So servers with less free
    ram will be preferred.

    Note: the weight for this function in default configuration
    is -1.0. With a -1.0 this function runs in reverse, so systems
    with the most free memory will be preferred.
    """
    return host_state.free_ram_mb


def weighted_sum(weighted_fns, host_states, weighing_properties):
    """Use the weighted-sum method to compute a score for an array of objects.

    Normalize the results of the objective-functions so that the weights are
    meaningful regardless of objective-function's range.

    :param host_list:    ``[(host, HostInfo()), ...]``
    :param weighted_fns: list of weights and functions like::

        [(weight, objective-functions), ...]

    :param weighing_properties: an arbitrary dict of values that can
        influence weights.

    :returns: a single WeightedHost object which represents the best
              candidate.
    """

    min_score, best_host = None, None
    for host_state in host_states:
        score = sum(weight * fn(host_state, weighing_properties)
                    for weight, fn in weighted_fns)
        if min_score is None or score < min_score:
            min_score, best_host = score, host_state

    return WeightedHost(min_score, host_state=best_host)
