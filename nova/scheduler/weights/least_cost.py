# Copyright (c) 2011-2012 OpenStack Foundation
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

NOTE(comstud): This is deprecated. One should use the RAMWeigher and/or
create other weight modules.
"""

from oslo.config import cfg

from nova import exception
from nova.openstack.common import importutils
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)

least_cost_opts = [
    cfg.ListOpt('least_cost_functions',
                default=None,
                help='Which cost functions the LeastCostScheduler should use'),
    cfg.FloatOpt('noop_cost_fn_weight',
                 default=1.0,
                 help='How much weight to give the noop cost function'),
    cfg.FloatOpt('compute_fill_first_cost_fn_weight',
                 default=None,
                 help='How much weight to give the fill-first cost function. '
                      'A negative value will reverse behavior: '
                      'e.g. spread-first'),
    ]

CONF = cfg.CONF
CONF.register_opts(least_cost_opts)


def noop_cost_fn(host_state, weight_properties):
    """Return a pre-weight cost of 1 for each host."""
    return 1


def compute_fill_first_cost_fn(host_state, weight_properties):
    """Higher weights win, so we should return a lower weight
    when there's more free ram available.

    Note: the weight modifier for this function in default configuration
    is -1.0. With -1.0 this function runs in reverse, so systems
    with the most free memory will be preferred.
    """
    return -host_state.free_ram_mb


def _get_cost_functions():
    """Returns a list of tuples containing weights and cost functions to
    use for weighing hosts
    """
    cost_fns_conf = CONF.least_cost_functions
    if cost_fns_conf is None:
        # The old default.  This will get fixed up below.
        fn_str = 'nova.scheduler.least_cost.compute_fill_first_cost_fn'
        cost_fns_conf = [fn_str]
    cost_fns = []
    for cost_fn_str in cost_fns_conf:
        short_name = cost_fn_str.split('.')[-1]
        if not (short_name.startswith('compute_') or
                short_name.startswith('noop')):
            continue
        # Fix up any old paths to the new paths
        if cost_fn_str.startswith('nova.scheduler.least_cost.'):
            cost_fn_str = ('nova.scheduler.weights.least_cost' +
                       cost_fn_str[25:])
        try:
            # NOTE: import_class is somewhat misnamed since
            # the weighing function can be any non-class callable
            # (i.e., no 'self')
            cost_fn = importutils.import_class(cost_fn_str)
        except ImportError:
            raise exception.SchedulerCostFunctionNotFound(
                    cost_fn_str=cost_fn_str)

        try:
            flag_name = "%s_weight" % cost_fn.__name__
            weight = getattr(CONF, flag_name)
        except AttributeError:
            raise exception.SchedulerWeightFlagNotFound(
                    flag_name=flag_name)
        # Set the original default.
        if (flag_name == 'compute_fill_first_cost_fn_weight' and
                weight is None):
            weight = -1.0
        cost_fns.append((weight, cost_fn))
    return cost_fns


def get_least_cost_weighers():
    cost_functions = _get_cost_functions()

    # Unfortunately we need to import this late so we don't have an
    # import loop.
    from nova.scheduler import weights

    class _LeastCostWeigher(weights.BaseHostWeigher):
        def weigh_objects(self, weighted_hosts, weight_properties):
            for host in weighted_hosts:
                host.weight = sum(weight * fn(host.obj, weight_properties)
                            for weight, fn in cost_functions)

    return [_LeastCostWeigher]
