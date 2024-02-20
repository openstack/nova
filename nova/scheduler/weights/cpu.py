# Copyright (c) 2016, Red Hat Inc.
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
CPU Weigher.  Weigh hosts by their CPU usage.

The default is to spread instances across all hosts evenly.  If you prefer
stacking, you can set the 'cpu_weight_multiplier' option (by configuration
or aggregate metadata) to a negative number and the weighing has the opposite
effect of the default.
"""
import math

import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights
from nova.weights import LOG
from ..manager import CORE_USAGE

CONF = nova.conf.CONF


def get_prefer_non_empty_machines_score(usable_cores, used_cores):
    free_cores = usable_cores - used_cores
    if free_cores == 0:
        return 0
    return 1


def get_prefer_most_unused_green_cores_score(gcpus_avl, gcpus_used):
    MAX_CPUS = 16.0
    free_gcpus = gcpus_avl - gcpus_used
    score = free_gcpus / MAX_CPUS
    return score


def get_prefer_guranteed_renewable_draw_score(type, rcpus_avl, rcpus_used, gcpus_avl, gcpus_used, vm_cpus):
    if type == 'regular':
        return 0

    rcpus_free = rcpus_avl - rcpus_used
    gcpus_free = gcpus_avl - gcpus_used
    rcpus_overflow = vm_cpus - rcpus_free

    if 0 < rcpus_overflow <= gcpus_free:
        return 1

    return 0


def get_worst_fit_on_green_cores_score(rcpus_avl, rcpus_used, gcpus_avl, gcpus_used, usable_cores, used_cores, vm_cpus):
    rcpus_free = rcpus_avl - rcpus_used
    gcpus_free = gcpus_avl - gcpus_used
    is_alloc_on_gcpus = rcpus_free < vm_cpus <= (rcpus_free + gcpus_free)
    if not is_alloc_on_gcpus:
        return 0

    score = 1 - get_best_fit_score(usable_cores=usable_cores, used_cores=used_cores, vm_cpus=vm_cpus)
    return score


def get_best_fit_score(usable_cores, used_cores, vm_cpus):
    free_cores = usable_cores - used_cores
    raw_score = free_cores - vm_cpus
    score = 1 - raw_score / usable_cores
    return score


def get_cpu_attrs(host_state):
    vcpus_used = host_state.vcpus_used
    vcpus_free = (host_state.vcpus_total * 1.0 - host_state.vcpus_used)
    rcpus_used = host_state.rcpus_used
    rcpus_free = (host_state.rcpus_total * 1.0 - host_state.rcpus_used)
    gcpus_used = host_state.gcpus_used
    gcpus_free = (host_state.gcpus_total * 1.0 - host_state.gcpus_used)
    return gcpus_free, gcpus_used, rcpus_free, rcpus_used, vcpus_free, vcpus_used


def get_final_weight(usable_cores, used_cores, gcpus_avl, gcpus_used, rcpus_avl, rcpus_used, type, vm_cpus):

    w1 = math.pow(3, 4) * get_prefer_non_empty_machines_score(
        usable_cores=usable_cores,
        used_cores=used_cores
    )
    w2 = math.pow(3, 3) * get_prefer_most_unused_green_cores_score(
        gcpus_avl=gcpus_avl,
        gcpus_used=gcpus_used
    )
    w3 = math.pow(3, 2) * get_prefer_guranteed_renewable_draw_score(
        type=type,
        rcpus_used=rcpus_used,
        gcpus_used=gcpus_used,
        gcpus_avl=gcpus_avl,
        rcpus_avl=rcpus_avl,
        vm_cpus=vm_cpus
    )
    w4 = math.pow(3, 1) * get_worst_fit_on_green_cores_score(
        usable_cores=usable_cores,
        used_cores=used_cores,
        gcpus_avl=gcpus_avl,
        gcpus_used=gcpus_used,
        rcpus_avl=rcpus_avl,
        rcpus_used=rcpus_used,
        vm_cpus=vm_cpus
    )
    w5 = math.pow(3, 0) * get_best_fit_score(
        usable_cores=usable_cores,
        used_cores=used_cores,
        vm_cpus=vm_cpus
    )

    final_weight = w1 + w2 + w3 + w4 + w5

    return final_weight


class CPUWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        host_ip = host_state.host_ip
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        core_usage = core_usage[0]

        rcpus_avl = core_usage['reg-cores-avl']
        gcpus_avl = core_usage['green-cores-avl']
        rcpus_used = core_usage['reg-cores-usg']
        gcpus_used = core_usage['green-cores-usg']

        usable_cores = rcpus_avl + gcpus_avl
        used_cores = rcpus_used + gcpus_used

        hints = weight_properties.scheduler_hints
        vm_type = hints['type'][0]

        vm_cpus = weight_properties.vcpus

        final_weight = get_final_weight(
            usable_cores=usable_cores,
            used_cores=used_cores,
            gcpus_avl=gcpus_avl,
            gcpus_used=gcpus_used,
            rcpus_avl=rcpus_avl,
            rcpus_used=rcpus_used,
            type=vm_type,
            vm_cpus=vm_cpus
        )
        return final_weight
