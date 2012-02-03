# Copyright (c) 2011 Openstack, LLC.
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

from nova import flags
from nova.openstack.common import cfg
from nova import log as logging


LOG = logging.getLogger('nova.scheduler.least_cost')

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
             default=1.0,
               help='How much weight to give the fill-first cost function'),
    ]

FLAGS = flags.FLAGS
FLAGS.add_options(least_cost_opts)

# TODO(sirp): Once we have enough of these rules, we can break them out into a
# cost_functions.py file (perhaps in a least_cost_scheduler directory)


class WeightedHost(object):
    """Reduced set of information about a host that has been weighed.
    This is an attempt to remove some of the ad-hoc dict structures
    previously used."""

    def __init__(self, weight, host_state=None, blob=None, zone=None):
        self.weight = weight
        self.blob = blob
        self.zone = zone

        # Local members. These are not returned outside of the Zone.
        self.host_state = host_state

    def to_dict(self):
        x = dict(weight=self.weight)
        if self.blob:
            x['blob'] = self.blob
        if self.host_state:
            x['host'] = self.host_state.host
        if self.zone:
            x['zone'] = self.zone
        return x


def noop_cost_fn(host_state, weighing_properties):
    """Return a pre-weight cost of 1 for each host"""
    return 1


def compute_fill_first_cost_fn(host_state, weighing_properties):
    """More free ram = higher weight. So servers will less free
    ram will be preferred."""
    return host_state.free_ram_mb


def weighted_sum(weighted_fns, host_states, weighing_properties):
    """Use the weighted-sum method to compute a score for an array of objects.
    Normalize the results of the objective-functions so that the weights are
    meaningful regardless of objective-function's range.

    host_list - [(host, HostInfo()), ...]
    weighted_fns - list of weights and functions like:
        [(weight, objective-functions), ...]
    weighing_properties is an arbitrary dict of values that can influence
        weights.

    Returns a single WeightedHost object which represents the best
    candidate.
    """

    # Make a grid of functions results.
    # One row per host. One column per function.
    scores = []
    for weight, fn in weighted_fns:
        scores.append([fn(host_state, weighing_properties)
                for host_state in host_states])

    # Adjust the weights in the grid by the functions weight adjustment
    # and sum them up to get a final list of weights.
    adjusted_scores = []
    for (weight, fn), row in zip(weighted_fns, scores):
        adjusted_scores.append([weight * score for score in row])

    # Now, sum down the columns to get the final score. Column per host.
    final_scores = [0.0] * len(host_states)
    for row in adjusted_scores:
        for idx, col in enumerate(row):
            final_scores[idx] += col

    # Super-impose the host_state into the scores so
    # we don't lose it when we sort.
    final_scores = [(final_scores[idx], host_state)
            for idx, host_state in enumerate(host_states)]

    final_scores = sorted(final_scores)
    weight, host_state = final_scores[0]  # Lowest score is the winner!
    return WeightedHost(weight, host_state=host_state)
