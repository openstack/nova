# Copyright 2018 IBM Corp.
#
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

from nova.virt.powervm.disk import driver as disk_dvr


class FakeDiskAdapter(disk_dvr.DiskAdapter):
    """A fake subclass of DiskAdapter.

    This is done so that the abstract methods/properties can be stubbed and the
    class can be instantiated for testing.
    """
    def _vios_uuids(self):
        pass

    def _disk_match_func(self, disk_type, instance):
        pass

    def disconnect_disk_from_mgmt(self, vios_uuid, disk_name):
        pass

    def capacity(self):
        pass

    def capacity_used(self):
        pass

    def detach_disk(self, instance):
        pass

    def delete_disks(self, storage_elems):
        pass

    def create_disk_from_image(self, context, instance, image_meta):
        pass

    def attach_disk(self, instance, disk_info, stg_ftsk):
        pass
