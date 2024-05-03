# Copyright (c) 2024 SAP SE
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

from oslo_log import log as logging

import nova.conf
from nova import context as nova_context
from nova import exception
from nova import objects
from nova.scheduler import filters
from nova.scheduler import utils

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class ResizeVcpuMaxUnitFilter(filters.BaseHostFilter):
    """Filter for resizing to a smaller flavor in VMware.

    This checks if the host can fit the current flavor of the
    instance. Reason is that in VMware, when a VM is resized
    to a smaller flavor, it's still being cloned with the
    initial size to the destination host and only resized
    afterward. If the original size had more vCPUs than
    the new target host can manage, the clone will fail.
    """

    RUN_ON_REBUILD = False

    def filter_all(self, filter_obj_list, spec_obj):
        if utils.is_non_vmware_spec(spec_obj):
            return filter_obj_list

        if not utils.request_is_resize(spec_obj):
            return filter_obj_list

        context = nova_context.get_admin_context()
        try:
            inst_mapping = objects.InstanceMapping.get_by_instance_uuid(
                context, spec_obj.instance_uuid)
            cell_mapping = inst_mapping.cell_mapping
        except exception.InstanceMappingNotFound:
            LOG.warning("Cannot find cell mapping for instance %s",
                        spec_obj.instance_uuid)
            return []

        try:
            with nova_context.target_cell(context, cell_mapping) as cctxt:
                instance = objects.Instance.get_by_uuid(
                    cctxt, spec_obj.instance_uuid,
                    expected_attrs=['flavor'])
        except exception.InstanceNotFound:
            LOG.warning("Cannot find instance %s",
                        spec_obj.instance_uuid)
            return []

        # Only account for resizing to smaller flavors
        if instance.flavor.vcpus <= spec_obj.vcpus:
            return filter_obj_list

        return [host_state for host_state in filter_obj_list
                if self._host_passes(host_state, instance)]

    @staticmethod
    def _host_passes(host_state, instance):
        try:
            vcpus_max = int(host_state.stats.get('vcpus_max_unit'))
        except (TypeError, ValueError):
            return False

        if not vcpus_max:
            return False

        if vcpus_max < instance.flavor.vcpus:
            LOG.debug('%(host_state)s has vcpus_max_unit=%(vcpus_max)s, thus '
                      'it cannot fit the instance with %(vcpus)s vCPUs.',
                      {'host_state': host_state,
                       'vcpus_max': vcpus_max,
                       'vcpus': instance.flavor.vcpus})
            return False

        return True
