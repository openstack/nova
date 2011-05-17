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
Helpful docstring here
"""

import collections

from nova import flags
from nova import log as logging
# TODO(sirp): this should be just `zone_aware` to match naming scheme
# TODO(sirp): perhaps all zone-aware stuff should go under a `zone_aware`
# module
from nova.scheduler import zone_aware_scheduler
from nova import utils

LOG = logging.getLogger('nova.scheduler.least_cost')

FLAGS = flags.FLAGS
flags.DEFINE_list('least_cost_scheduler_cost_functions',
                  ['nova.scheduler.least_cost.noop_cost_fn'],
                  'Which cost functions the LeastCostScheduler should use.')


flags.DEFINE_integer('noop_cost_fn_weight', 1,
                     'How much weight to give the noop cost function')
def noop_cost_fn(host):
    """Return a pre-weight cost of 1 for each host"""
    return 1


class LeastCostScheduler(zone_aware_scheduler.ZoneAwareScheduler):
    def get_cost_fns(self):
        """Returns a list of tuples containing weights and cost functions to
        use for weighing hosts
        """
        cost_fns = []
        for cost_fn_str in FLAGS.least_cost_scheduler_cost_functions:

            try:
                # NOTE(sirp): import_class is somewhat misnamed since it can
                # any callable from a module
                cost_fn = utils.import_class(cost_fn_str)
            except exception.ClassNotFound:
                raise exception.SchedulerCostFunctionNotFound(
                    cost_fn_str=cost_fn_str)
          
            try:
                weight = getattr(FLAGS, "%s_weight" % cost_fn.__name__)
            except AttributeError:
                raise exception.SchedulerWeightFlagNotFound(
                    flag_name=flag_name)

            cost_fns.append((weight, cost_fn))

        return cost_fns

    def weigh_hosts(self, num, request_spec, hosts):
        """Returns a list of dictionaries of form:
            [ {weight: weight, hostname: hostname} ]"""
        # FIXME(sirp): weigh_hosts should handle more than just instances
        hostnames = [hostname for hostname, _ in hosts]

        cost_fns = self.get_cost_fns()
        costs = weighted_sum(domain=hosts, weighted_fns=cost_fns)
        
        weighted = []
        for cost, hostname in zip(costs, hostnames):
            weight_dict = dict(weight=cost, hostname=hostname)
            weighted.append(weight_dict)
        return weighted 


def normalize_list(L):
    """Normalize an array of numbers such that each element satisfies:
        0 <= e <= 1"""
    if not L:
        return L
    max_ = max(L)
    if max_ > 0:
        return [(float(e) / max_) for e in L]
    return L


def weighted_sum(domain, weighted_fns, normalize=True):
    """Use the weighted-sum method to compute a score for an array of objects.
    Normalize the results of the objective-functions so that the weights are
    meaningful regardless of objective-function's range.
    
    domain - input to be scored
    weighted_fns - list of weights and functions like:
        [(weight, objective-functions)]

    Returns an unsorted of scores. To pair with hosts do: zip(scores, hosts)
    """
    # Table of form:
    #   { domain1: [score1, score2, ..., scoreM]
    #     ...
    #     domainN: [score1, score2, ..., scoreM] }
    score_table = collections.defaultdict(list)
    for weight, fn in weighted_fns:
        scores = [fn(elem) for elem in domain]

        if normalize:
            norm_scores = normalize_list(scores)
        else:
            norm_scores = scores

        for idx, score in enumerate(norm_scores):
            weighted_score = score * weight
            score_table[idx].append(weighted_score)

    # Sum rows in table to compute score for each element in domain
    domain_scores = []
    for idx in sorted(score_table):
        elem_score = sum(score_table[idx])
        elem = domain[idx]
        domain_scores.append(elem_score)

    return domain_scores
