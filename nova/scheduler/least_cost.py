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
Least Cost Scheduler is a mechanism for choosing which host machines to
provision a set of resources to. The input of the least-cost-scheduler is a
set of objective-functions, called the 'cost-functions', a weight for each
cost-function, and a list of candidate hosts (gathered via FilterHosts).

The cost-function and weights are tabulated, and the host with the least cost
is then selected for provisioning.
"""


import collections

from nova import flags
from nova import log as logging
from nova.scheduler import base_scheduler
from nova import utils
from nova import exception

LOG = logging.getLogger('nova.scheduler.least_cost')

FLAGS = flags.FLAGS
flags.DEFINE_list('least_cost_scheduler_cost_functions',
        ['nova.scheduler.least_cost.noop_cost_fn'],
        'Which cost functions the LeastCostScheduler should use.')


# TODO(sirp): Once we have enough of these rules, we can break them out into a
# cost_functions.py file (perhaps in a least_cost_scheduler directory)
flags.DEFINE_integer('noop_cost_fn_weight', 1,
             'How much weight to give the noop cost function')
flags.DEFINE_integer('compute_fill_first_cost_fn_weight', 1,
             'How much weight to give the fill-first cost function')


def noop_cost_fn(host):
    """Return a pre-weight cost of 1 for each host"""
    return 1


def compute_fill_first_cost_fn(host):
    """Prefer hosts that have less ram available, filter_hosts will exclude
    hosts that don't have enough ram.
    """
    hostname, service = host
    caps = service.get("compute", {})
    free_mem = caps.get("host_memory_free", 0)
    return free_mem


def normalize_list(L):
    """Normalize an array of numbers such that each element satisfies:
        0 <= e <= 1
    """
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

    Returns an unsorted list of scores. To pair with hosts do:
        zip(scores, hosts)
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
        domain_scores.append(elem_score)
    return domain_scores


class LeastCostScheduler(base_scheduler.BaseScheduler):
    def __init__(self, *args, **kwargs):
        self.cost_fns_cache = {}
        super(LeastCostScheduler, self).__init__(*args, **kwargs)

    def get_cost_fns(self, topic):
        """Returns a list of tuples containing weights and cost functions to
        use for weighing hosts
        """
        if topic in self.cost_fns_cache:
            return self.cost_fns_cache[topic]
        cost_fns = []
        for cost_fn_str in FLAGS.least_cost_scheduler_cost_functions:
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

        self.cost_fns_cache[topic] = cost_fns
        return cost_fns

    def weigh_hosts(self, topic, request_spec, hosts):
        """Returns a list of dictionaries of form:
           [ {weight: weight, hostname: hostname, capabilities: capabs} ]
        """
        cost_fns = self.get_cost_fns(topic)
        costs = weighted_sum(domain=hosts, weighted_fns=cost_fns)

        weighted = []
        weight_log = []
        for cost, (hostname, service) in zip(costs, hosts):
            caps = service[topic]
            weight_log.append("%s: %s" % (hostname, "%.2f" % cost))
            weight_dict = dict(weight=cost, hostname=hostname,
                    capabilities=caps)
            weighted.append(weight_dict)

        LOG.debug(_("Weighted Costs => %s") % weight_log)
        return weighted
