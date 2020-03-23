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
from nova.exception import ObjectActionError
from nova.scheduler import utils
from nova.scheduler import weights
from nova.utils import is_baremetal_flavor
import six

CONF = nova.conf.CONF


class PreferSameHostOnResizeWeigher(weights.BaseHostWeigher):
    minval = 0

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'prefer_same_host_resize_weight_multiplier',
            CONF.filter_scheduler.prefer_same_host_resize_weight_multiplier)

    def _is_resize(self, cur_flavor, dest_flavor):
        """Return True if `cur_flavor` is different from `dest_flavor`.
        Return False otherwise.
        """
        try:
            return cur_flavor.id != dest_flavor.id
        except ObjectActionError as e:
            if 'obj_load_attr' in six.text_type(e):
                # Note(jakob): If for some weird reason, id cannot be found,
                # assume it's a resize. There is not much to break by
                # preferring the same host.
                return True
            raise e

    def _weigh_object(self, host_state, request_spec):
        """Return 1 for about-to-be-resized instances where the host is the
        instance's current host. Return 0 otherwise.
        """
        if ((request_spec.instance_uuid not in host_state.instances) or
                utils.request_is_rebuild(request_spec)):
            return 0.0

        instance = host_state.instances[request_spec.instance_uuid]
        if (is_baremetal_flavor(instance.flavor) or
                is_baremetal_flavor(request_spec.flavor)):
            return 0.0

        if self._is_resize(instance.flavor, request_spec.flavor):
            return 1.0
        return 0.0
