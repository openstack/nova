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

from nova.api.openstack import common

INSTANCE_DIAGNOSTICS_PRIMITIVE_FIELDS = (
    'state', 'driver', 'hypervisor', 'hypervisor_os', 'uptime', 'config_drive',
    'num_cpus', 'num_nics', 'num_disks'
)

INSTANCE_DIAGNOSTICS_LIST_FIELDS = {
    'disk_details': ('read_bytes', 'read_requests', 'write_bytes',
                     'write_requests', 'errors_count'),
    'cpu_details': ('id', 'time', 'utilisation'),
    'nic_details': ('mac_address', 'rx_octets', 'rx_errors', 'rx_drop',
                    'rx_packets', 'rx_rate', 'tx_octets', 'tx_errors',
                    'tx_drop', 'tx_packets', 'tx_rate')
}

INSTANCE_DIAGNOSTICS_OBJECT_FIELDS = {'memory_details': ('maximum', 'used')}


class ViewBuilder(common.ViewBuilder):
    @staticmethod
    def _get_obj_field(obj, field):
        if obj and obj.obj_attr_is_set(field):
            return getattr(obj, field)
        return None

    def instance_diagnostics(self, diagnostics):
        """Return a dictionary with instance diagnostics."""
        diagnostics_dict = {}
        for field in INSTANCE_DIAGNOSTICS_PRIMITIVE_FIELDS:
            diagnostics_dict[field] = self._get_obj_field(diagnostics, field)

        for list_field in INSTANCE_DIAGNOSTICS_LIST_FIELDS:
            diagnostics_dict[list_field] = []
            list_obj = getattr(diagnostics, list_field)

            for obj in list_obj:
                obj_dict = {}
                for field in INSTANCE_DIAGNOSTICS_LIST_FIELDS[list_field]:
                    obj_dict[field] = self._get_obj_field(obj, field)
                diagnostics_dict[list_field].append(obj_dict)

        for obj_field in INSTANCE_DIAGNOSTICS_OBJECT_FIELDS:
            diagnostics_dict[obj_field] = {}
            obj = self._get_obj_field(diagnostics, obj_field)
            for field in INSTANCE_DIAGNOSTICS_OBJECT_FIELDS[obj_field]:
                diagnostics_dict[obj_field][field] = self._get_obj_field(
                    obj, field)

        return diagnostics_dict
