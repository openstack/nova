# Copyright (c) 2020 OpenStack Foundation
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
Prefer resize to same host weigher. Resizing an instance gives the current host
a higher priority.

This weigher ignores any instances which are:
 * new instances (or unshelving)
 * not resizing (a.k.a. migrating or rebuilding)
 * baremetal
"""
import nova.conf
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF


class PreferSameHostOnResizeWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'prefer_same_host_resize_weight_multiplier',
            CONF.filter_scheduler.prefer_same_host_resize_weight_multiplier)

    def _weigh_object(self, host_state, request_spec):
        """Return 1 for about-to-be-resized instances where the host is the
        instance's current host. Return 0 otherwise.
        """
        if not utils.request_is_resize(request_spec):
            return 0.0

        if utils.is_non_vmware_spec(request_spec):
            return 0.0

        instance_host = request_spec.get_scheduler_hint('source_host')

        if instance_host != host_state.host:
            return 0.0

        return 1.0
