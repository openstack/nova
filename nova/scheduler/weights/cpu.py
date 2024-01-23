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


def get_prefer_non_empty_machines_score(used_gc, free_gc, used_rc, free_rc):
    if used_gc + used_rc > 0:
        return 1
    else:
        return 0


def get_prefer_most_unused_green_cores_score(used_gc, free_gc, used_rc, free_rc):
    if free_gc + used_gc == 0:
        return 0
    else:
        return free_gc / (free_gc + used_gc)


def get_prefer_guranteed_renewable_draw_score(used_gc, free_gc, used_rc, free_rc, type, vm_vcpus):
    if type == 'regular':
        return 0

    overflow = vm_vcpus - free_rc
    if 0 < overflow <= free_gc:
        return 1
    else:
        return 0


def get_worst_fit_on_green_cores_score(used_gc, free_gc, used_rc, free_rc, type, vm_vcpus):
    if free_gc + used_gc == 0:
        return 0
    overflow = vm_vcpus - free_rc
    if 0 < overflow <= free_gc:
        return free_gc / (free_gc + used_gc)
    else:
        return 0


def get_best_fit_on_green_cores_score(used_vcpu, free_vcpu):
    return 1 - (free_vcpu / (used_vcpu + free_vcpu))


def get_cpu_attrs(host_state):
    vcpus_used = host_state.vcpus_used
    vcpus_free = (host_state.vcpus_total * 1.0 - host_state.vcpus_used)
    rcpus_used = host_state.rcpus_used
    rcpus_free = (host_state.rcpus_total * 1.0 - host_state.rcpus_used)
    gcpus_used = host_state.gcpus_used
    gcpus_free = (host_state.gcpus_total * 1.0 - host_state.gcpus_used)
    return gcpus_free, gcpus_used, rcpus_free, rcpus_used, vcpus_free, vcpus_used


class CPUWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'cpu_weight_multiplier',
            CONF.filter_scheduler.cpu_weight_multiplier)

    def _weigh_object(self, host_state, weight_properties):
        """Higher weights win.  We want spreading to be the default."""
        LOG.debug("tharindu-green-cores: CORE_USAGE['core_usage'] %(weight_properties)s", {'weight_properties': CORE_USAGE['core_usage']})
        LOG.debug("tharindu-green-cores@weighter: host ip %(ip)s", {'ip': host_state.host_ip})
        LOG.debug("tharindu-green-cores@weighter: weight_properties %(weight_properties)s", {'weight_properties': weight_properties})
        # vcpus_free = (
        #     host_state.vcpus_total * host_state.cpu_allocation_ratio -
        #     host_state.vcpus_used)
        # return vcpus_free

        host_ip = host_state.host_ip
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        LOG.debug("tharindu-green-cores@cpu: host_ip %(host_ip)s", {'host_ip': host_ip})
        LOG.debug("tharindu-green-cores@cpu: core_usage %(core_usage)s", {'core_usage': core_usage})
        core_usage = core_usage[0]

        rcpus_avl = core_usage['reg-cores-avl']
        gcpus_avl = core_usage['green-cores-avl']
        rcpus_used = core_usage['reg-cores-usg']
        gcpus_used = core_usage['green-cores-usg']
        gcpus_free = gcpus_avl - gcpus_used
        rcpus_free = rcpus_avl - rcpus_used
        vcpus_used = rcpus_used + gcpus_used
        vcpus_free = rcpus_free + gcpus_free

        hints = weight_properties.scheduler_hints
        type = hints['type'][0]

        w1 = math.pow(3, 4) * get_prefer_non_empty_machines_score(gcpus_used, gcpus_free, rcpus_used, rcpus_free)
        w2 = math.pow(3, 3) * get_prefer_most_unused_green_cores_score(gcpus_used, gcpus_free, rcpus_used, rcpus_free)
        w3 = math.pow(3, 2) * get_prefer_guranteed_renewable_draw_score(gcpus_used, gcpus_free, rcpus_used, rcpus_free, type, weight_properties.vcpus)
        w4 = math.pow(3, 1) * get_worst_fit_on_green_cores_score(gcpus_used, gcpus_free, rcpus_used, rcpus_free, type, weight_properties.vcpus)
        w5 = math.pow(3, 0) * get_best_fit_on_green_cores_score(vcpus_used, vcpus_free)

        final_weight = w1 + w2 + w3 + w4 + w5
        return final_weight
