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
Image Properties Weigher. Weigh hosts by the image metadata properties
related to the existing instances.

A positive value will favor hosts with the same image properties (packing
strategy) while a negative value will follow a spread strategy that will favor
hosts not already having instances with those image properties.
The default value of the multiplier is 0, which disables the weigher.
"""

import nova.conf
from nova import exception
from nova import objects
from nova.scheduler import utils
from nova.scheduler import weights

CONF = nova.conf.CONF


class ImagePropertiesWeigher(weights.BaseHostWeigher):
    def __init__(self):
        self._parse_setting()

    def _parse_setting(self):
        self.setting = dict(utils.parse_options(
            CONF.filter_scheduler.image_props_weight_setting,
            sep='=', converter=float,
            name="filter_scheduler.image_props_weight_setting"))

    def weight_multiplier(self, host_state):
        """Override the weight multiplier."""
        return utils.get_weight_multiplier(
            host_state, 'image_props_weight_multiplier',
            CONF.filter_scheduler.image_props_weight_multiplier)

    def _weigh_object(self, host_state, request_spec):
        """Higher weights win.  We want to choose hosts with the more common
           existing image properties that are used by instances by default.
           If you want to spread instances with the same properties between
           hosts, change the multiplier value to a negative number.
        """

        weight = 0.0

        # Disable this weigher if we don't use it as it's a bit costly.
        if CONF.filter_scheduler.image_props_weight_multiplier == 0.0:
            return weight

        # request_spec is a RequestSpec object which can have its image
        # field set to None
        if request_spec.image:
            # List values aren't hashable so we need to stringify them.
            requested_props = {(key, f"{value}") for key, value in
                request_spec.image.properties.to_dict().items()}
        else:
            requested_props = set()

        existing_props = []

        insts = objects.InstanceList(objects=host_state.instances.values())
        # system_metadata isn't loaded yet, let's do this.
        insts.fill_metadata()

        for inst in insts:
            try:
                props = {(key, str(value)) for key, value in
                         inst.image_meta.properties.to_dict().items()
                         } if inst.image_meta else set()
            except exception.InstanceNotFound:
                # the host state can be a bit stale as the instance could no
                # longer exist on the host if the instance deletion arrives
                # before the scheduler gets the RPC message of the deletion
                props = set()
            # We want to unpack the set of tuples as items to the total list
            # of properties we need to compare.
            existing_props.extend(tup for tup in props)

        common_props = requested_props & set(existing_props)

        for (prop, value) in common_props:
            if self.setting:
                # Calculate the weigh for each property by what was set
                # If it wasn't defined, then don't weigh this property.
                weight += self.setting.get(
                            prop, 0.0) * existing_props.count((prop, value))
            else:
                # By default, all properties are weighed evenly.
                weight += existing_props.count((prop, value))
        return weight
