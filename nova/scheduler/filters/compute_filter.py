# Copyright (c) 2012 OpenStack, LLC.
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

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova import utils


LOG = logging.getLogger(__name__)


class ComputeFilter(filters.BaseHostFilter):
    """Filter on active Compute nodes that satisfy the instance properties"""

    def _instance_supported(self, capabilities, instance_meta):
        """Check if the instance is supported by the hypervisor.

        The instance may specify an architecture, hypervisor, and
        vm_mode, e.g. (x86_64, kvm, hvm).
        """
        inst_arch = instance_meta.get('image_architecture', None)
        inst_h_type = instance_meta.get('image_hypervisor_type', None)
        inst_vm_mode = instance_meta.get('image_vm_mode', None)
        inst_props_req = (inst_arch, inst_h_type, inst_vm_mode)

        # Supported if no compute-related instance properties are specified
        if not any(inst_props_req):
            return True

        supp_instances = capabilities.get('supported_instances', None)
        # Not supported if an instance property is requested but nothing
        # advertised by the host.
        if not supp_instances:
            LOG.debug(_("Instance contains properties %(instance_meta)s, "
                        "but no corresponding capabilities are advertised "
                        "by the compute node"), locals())
            return False

        def _compare_props(props, other_props):
            for i in props:
                if i and i not in other_props:
                    return False
            return True

        for supp_inst in supp_instances:
            if _compare_props(inst_props_req, supp_inst):
                LOG.debug(_("Instance properties %(instance_meta)s "
                            "are satisfied by compute host capabilities "
                            "%(capabilities)s"), locals())
                return True

        LOG.debug(_("Instance contains properties %(instance_meta)s "
                    "that are not provided by the compute node "
                    "capabilities %(capabilities)s"), locals())
        return False

    def host_passes(self, host_state, filter_properties):
        """Check if host passes instance compute properties.

        Returns True for active compute nodes that satisfy
        the compute properties specified in the instance.
        """
        spec = filter_properties.get('request_spec', {})
        instance_props = spec.get('instance_properties', {})
        instance_meta = instance_props.get('system_metadata', {})
        instance_type = filter_properties.get('instance_type')
        if host_state.topic != 'compute' or not instance_type:
            return True
        capabilities = host_state.capabilities
        service = host_state.service

        if not utils.service_is_up(service) or service['disabled']:
            LOG.debug(_("%(host_state)s is disabled or has not been "
                    "heard from in a while"), locals())
            return False
        if not capabilities.get("enabled", True):
            LOG.debug(_("%(host_state)s is disabled via capabilities"),
                    locals())
            return False
        if not self._instance_supported(capabilities, instance_meta):
            LOG.debug(_("%(host_state)s does not support requested "
                        "instance_properties"), locals())
            return False
        return True
