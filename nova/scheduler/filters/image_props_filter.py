# Copyright (c) 2011-2012 OpenStack Foundation
# Copyright (c) 2012 Canonical Ltd
# Copyright (c) 2012 SUSE LINUX Products GmbH
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

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.scheduler import filters


LOG = logging.getLogger(__name__)


class ImagePropertiesFilter(filters.BaseHostFilter):
    """Filter compute nodes that satisfy instance image properties.

    The ImagePropertiesFilter filters compute nodes that satisfy
    any architecture, hypervisor type, or virtual machine mode properties
    specified on the instance's image properties.  Image properties are
    contained in the image dictionary in the request_spec.
    """

    # Image Properties and Compute Capabilities do not change within
    # a request
    run_filter_once_per_request = True

    def _instance_supported(self, host_state, image_props):
        img_arch = image_props.get('architecture', None)
        img_h_type = image_props.get('hypervisor_type', None)
        img_vm_mode = image_props.get('vm_mode', None)
        checked_img_props = (img_arch, img_h_type, img_vm_mode)

        # Supported if no compute-related instance properties are specified
        if not any(checked_img_props):
            return True

        supp_instances = host_state.supported_instances
        # Not supported if an instance property is requested but nothing
        # advertised by the host.
        if not supp_instances:
            LOG.debug(_("Instance contains properties %(image_props)s, "
                        "but no corresponding supported_instances are "
                        "advertised by the compute node"),
                        {'image_props': image_props})
            return False

        def _compare_props(props, other_props):
            for i in props:
                if i and i not in other_props:
                    return False
            return True

        for supp_inst in supp_instances:
            if _compare_props(checked_img_props, supp_inst):
                LOG.debug(_("Instance properties %(image_props)s "
                            "are satisfied by compute host supported_instances"
                            "%(supp_instances)s"),
                            {'image_props': image_props,
                             'supp_instances': supp_instances})
                return True

        LOG.debug(_("Instance contains properties %(image_props)s "
                    "that are not provided by the compute node "
                    "supported_instances %(supp_instances)s"),
                  {'image_props': image_props,
                   'supp_instances': supp_instances})
        return False

    def host_passes(self, host_state, filter_properties):
        """Check if host passes specified image properties.

        Returns True for compute nodes that satisfy image properties
        contained in the request_spec.
        """
        spec = filter_properties.get('request_spec', {})
        image_props = spec.get('image', {}).get('properties', {})

        if not self._instance_supported(host_state, image_props):
            LOG.debug(_("%(host_state)s does not support requested "
                        "instance_properties"), {'host_state': host_state})
            return False
        return True
