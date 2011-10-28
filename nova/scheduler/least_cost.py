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


import collections

from nova import flags
from nova import log as logging
from nova import utils
from nova import exception

LOG = logging.getLogger('nova.scheduler.least_cost')

FLAGS = flags.FLAGS
flags.DEFINE_list('least_cost_functions',
        ['nova.scheduler.least_cost.compute_fill_first_cost_fn'],
        'Which cost functions the LeastCostScheduler should use.')


# TODO(sirp): Once we have enough of these rules, we can break them out into a
# cost_functions.py file (perhaps in a least_cost_scheduler directory)
flags.DEFINE_float('noop_cost_fn_weight', 1.0,
             'How much weight to give the noop cost function')
flags.DEFINE_float('compute_fill_first_cost_fn_weight', 1.0,
             'How much weight to give the fill-first cost function')


COST_FUNCTION_CACHE = {}


class WeightedHost(object):
    """Reduced set of information about a host that has been weighed.
    This is an attempt to remove some of the ad-hoc dict structures
    previously used."""

    def __init__(self, weight, host=None, blob=None, zone=None, hostinfo=None):
        self.weight = weight
        self.blob = blob
        self.host = host
        self.zone = zone

        # Local members. These are not returned outside of the Zone.
        self.hostinfo = hostinfo

    def to_dict(self):
        x = dict(weight=self.weight)
        if self.blob:
            x['blob'] = self.blob
        if self.host:
            x['host'] = self.host
        if self.zone:
            x['zone'] = self.zone
        return x


def noop_cost_fn(host_info):
    """Return a pre-weight cost of 1 for each host"""
    return 1


def compute_fill_first_cost_fn(host_info):
    """More free ram = higher weight. So servers will less free
    ram will be preferred."""
    return host_info.free_ram_mb


def normalize_grid(grid):
    """Normalize a grid of numbers by row."""
    if not grid:
        return [[]]

    normalized = []
    for row in grid:
        if not row:
            normalized.append([])
            continue
        mx = float(max(row))
        if abs(mx) < 0.001:
            normalized = [0.0] * len(row)
            continue
        normalized.append([float(col) / mx for col in row])
    return normalized


def weighted_sum(host_list, weighted_fns):
    """Use the weighted-sum method to compute a score for an array of objects.
    Normalize the results of the objective-functions so that the weights are
    meaningful regardless of objective-function's range.

    host_list - [(host, HostInfo()), ...]
    weighted_fns - list of weights and functions like:
        [(weight, objective-functions), ...]

    Returns a single WeightedHost object which represents the best
    candidate.
    """

    # Make a grid of functions results.
    # One row per host. One column per function.
    scores = []
    for weight, fn in weighted_fns:
        scores.append([fn(host_info) for hostname, host_info in host_list])
    scores = normalize_grid(scores)

    # Adjust the weights in the grid by the functions weight adjustment
    # and sum them up to get a final list of weights.
    adjusted_scores = []
    for (weight, fn), row in zip(weighted_fns, scores):
        adjusted_scores.append([weight * score for score in row])

    # Now, sum down the columns to get the final score. Column per host.
    final_scores = [0.0] * len(host_list)
    for row in adjusted_scores:
        for idx, col in enumerate(row):
            final_scores[idx] += col

    # Super-impose the hostinfo into the scores so
    # we don't lose it when we sort.
    final_scores = [(final_scores[idx], host_tuple)
                    for idx, host_tuple in enumerate(host_list)]

    final_scores = sorted(final_scores)
    weight, (host, hostinfo) = final_scores[0]  # Lowest score is the winner!
    return WeightedHost(weight, host=host, hostinfo=hostinfo)


def get_cost_fns(topic=None):
    """Returns a list of tuples containing weights and cost functions to
    use for weighing hosts
    """
    global COST_FUNCTION_CACHE
    cost_function_cache = COST_FUNCTION_CACHE

    if topic is None:
        # Schedulers only support compute right now.
        topic = "compute"
    if topic in cost_function_cache:
        return cost_function_cache[topic]

    cost_fns = []
    for cost_fn_str in FLAGS.least_cost_functions:
        if '.' in cost_fn_str:
            short_name = cost_fn_str.split('.')[-1]
        else:
            short_name = cost_fn_str
            cost_fn_str = "%s.%s.%s" % (
                    __name__, self.__class__.__name__, short_name)
        if not (short_name.startswith('%s_' % topic) or
                short_name.startswith('noop')):
            continue

        try:
            # NOTE(sirp): import_class is somewhat misnamed since it can
            # any callable from a module
            cost_fn = utils.import_class(cost_fn_str)
        except exception.ClassNotFound:
            raise exception.SchedulerCostFunctionNotFound(
                    cost_fn_str=cost_fn_str)

        try:
            flag_name = "%s_weight" % cost_fn.__name__
            weight = getattr(FLAGS, flag_name)
        except AttributeError:
            raise exception.SchedulerWeightFlagNotFound(
                    flag_name=flag_name)
        cost_fns.append((weight, cost_fn))

    cost_function_cache[topic] = cost_fns
    return cost_fns


def weigh_hosts(request_spec, host_list):
    """Returns the best host as a WeightedHost."""
    cost_fns = get_cost_fns()
    return weighted_sum(host_list, cost_fns)
