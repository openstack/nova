import collections

# TODO(sirp): this should be just `zone_aware` to match naming scheme
# TODO(sirp): perhaps all zone-aware stuff should go under a `zone_aware`
# module
from nova.scheduler import zone_aware_scheduler

class LeastCostScheduler(zone_aware_scheduler.ZoneAwareScheduler):
    def get_cost_fns(self):
        """Returns a list of tuples containing weights and cost functions to
        use for weighing hosts
        """
        cost_fns = []

        return cost_fns

    def weigh_hosts(self, num, specs, hosts):
        """
        Returns a list of dictionaries of form:
            [ {weight: weight, hostname: hostname} ]
        """
        # FIXME(sirp): weigh_hosts should handle more than just instances
        cost_fns = []
        hosts = []
        cost_hosts = weighted_sum(domain=hosts, weighted_fns=self.get_cost_fns())

        # TODO convert hosts back to hostnames
        weight_hostnames = []
        return weight_hostnames 

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
    """
    Use the weighted-sum method to compute a score for an array of objects.
    Normalize the results of the objective-functions so that the weights are
    meaningful regardless of objective-function's range.
    
    domain - input to be scored
    weighted_fns - list of weights and functions like:
        [(weight, objective-functions)]

    Returns an unsorted list like: [(score, elem)]
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
