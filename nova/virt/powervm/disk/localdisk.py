# Copyright 2013 OpenStack Foundation
# Copyright 2015, 2018 IBM Corp.
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

import oslo_log.log as logging
from pypowervm import const as pvm_const
from pypowervm.tasks import scsi_mapper as tsk_map
from pypowervm.tasks import storage as tsk_stg
from pypowervm.wrappers import storage as pvm_stg
from pypowervm.wrappers import virtual_io_server as pvm_vios

from nova import conf
from nova import exception
from nova.image import glance
from nova.virt.powervm.disk import driver as disk_dvr
from nova.virt.powervm import vm

LOG = logging.getLogger(__name__)
CONF = conf.CONF
IMAGE_API = glance.API()


class LocalStorage(disk_dvr.DiskAdapter):

    def __init__(self, adapter, host_uuid):
        super(LocalStorage, self).__init__(adapter, host_uuid)

        self.capabilities = {
            'shared_storage': False,
            'has_imagecache': False,
            # NOTE(efried): 'snapshot' capability set dynamically below.
        }

        # Query to get the Volume Group UUID
        if not CONF.powervm.volume_group_name:
            raise exception.OptRequiredIfOtherOptValue(
                if_opt='disk_driver', if_value='localdisk',
                then_opt='volume_group_name')
        self.vg_name = CONF.powervm.volume_group_name
        vios_w, vg_w = tsk_stg.find_vg(adapter, self.vg_name)
        self._vios_uuid = vios_w.uuid
        self.vg_uuid = vg_w.uuid
        # Set the 'snapshot' capability dynamically. If we're hosting I/O on
        # the management partition, we can snapshot. If we're hosting I/O on
        # traditional VIOS, we are limited by the fact that a VSCSI device
        # can't be mapped to two partitions (the VIOS and the management) at
        # once.
        self.capabilities['snapshot'] = self.mp_uuid == self._vios_uuid
        LOG.info("Local Storage driver initialized: volume group: '%s'",
                 self.vg_name)

    @property
    def _vios_uuids(self):
        """List the UUIDs of the Virtual I/O Servers hosting the storage.

        For localdisk, there's only one.
        """
        return [self._vios_uuid]

    @staticmethod
    def _disk_match_func(disk_type, instance):
        """Return a matching function to locate the disk for an instance.

        :param disk_type: One of the DiskType enum values.
        :param instance: The instance whose disk is to be found.
        :return: Callable suitable for the match_func parameter of the
                 pypowervm.tasks.scsi_mapper.find_maps method.
        """
        disk_name = LocalStorage._get_disk_name(
            disk_type, instance, short=True)
        return tsk_map.gen_match_func(pvm_stg.VDisk, names=[disk_name])

    @property
    def capacity(self):
        """Capacity of the storage in gigabytes."""
        vg_wrap = self._get_vg_wrap()
        return float(vg_wrap.capacity)

    @property
    def capacity_used(self):
        """Capacity of the storage in gigabytes that is used."""
        vg_wrap = self._get_vg_wrap()
        # Subtract available from capacity
        return float(vg_wrap.capacity) - float(vg_wrap.available_size)

    def delete_disks(self, storage_elems):
        """Removes the specified disks.

        :param storage_elems: A list of the storage elements that are to be
                              deleted. Derived from the return value from
                              detach_disk.
        """
        # All of localdisk is done against the volume group. So reload
        # that (to get new etag) and then update against it.
        tsk_stg.rm_vg_storage(self._get_vg_wrap(), vdisks=storage_elems)

    def detach_disk(self, instance):
        """Detaches the storage adapters from the image disk.

        :param instance: Instance to disconnect the image for.
        :return: A list of all the backing storage elements that were
                 disconnected from the I/O Server and VM.
        """
        lpar_uuid = vm.get_pvm_uuid(instance)

        # Build the match function
        match_func = tsk_map.gen_match_func(pvm_stg.VDisk)

        vios_w = pvm_vios.VIOS.get(
            self._adapter, uuid=self._vios_uuid, xag=[pvm_const.XAG.VIO_SMAP])

        # Remove the mappings.
        mappings = tsk_map.remove_maps(
            vios_w, lpar_uuid, match_func=match_func)

        # Update the VIOS with the removed mappings.
        vios_w.update()

        return [x.backing_storage for x in mappings]

    def disconnect_disk_from_mgmt(self, vios_uuid, disk_name):
        """Disconnect a disk from the management partition.

        :param vios_uuid: The UUID of the Virtual I/O Server serving the
                          mapping.
        :param disk_name: The name of the disk to unmap.
        """
        tsk_map.remove_vdisk_mapping(self._adapter, vios_uuid, self.mp_uuid,
                                     disk_names=[disk_name])
        LOG.info("Unmapped boot disk %(disk_name)s from the management "
                 "partition from Virtual I/O Server %(vios_name)s.",
                 {'disk_name': disk_name, 'mp_uuid': self.mp_uuid,
                 'vios_name': vios_uuid})

    def create_disk_from_image(self, context, instance, image_meta):
        """Creates a disk and copies the specified image to it.

        Cleans up the created disk if an error occurs.

        :param context: nova context used to retrieve image from glance
        :param instance: instance to create the disk for.
        :param image_meta: The metadata of the image of the instance.
        :return: The backing pypowervm storage object that was created.
        """
        LOG.info('Create disk.', instance=instance)

        return self._upload_image(context, instance, image_meta)

        # TODO(esberglu): Copy vdisk when implementing image cache.

    def _upload_image(self, context, instance, image_meta):
        """Upload a new image.

        :param context: Nova context used to retrieve image from glance.
        :param image_meta: The metadata of the image of the instance.
        :return: The virtual disk containing the image.
        """

        img_name = self._get_disk_name(disk_dvr.DiskType.BOOT, instance,
                                       short=True)

        # TODO(esberglu) Add check for cached image when adding imagecache.

        return tsk_stg.upload_new_vdisk(
            self._adapter, self._vios_uuid, self.vg_uuid,
            disk_dvr.IterableToFileAdapter(
                IMAGE_API.download(context, image_meta.id)), img_name,
            image_meta.size, d_size=image_meta.size,
            upload_type=tsk_stg.UploadType.IO_STREAM,
            file_format=image_meta.disk_format)[0]

    def attach_disk(self, instance, disk_info, stg_ftsk):
        """Attaches the disk image to the Virtual Machine.

        :param instance: nova instance to connect the disk to.
        :param disk_info: The pypowervm storage element returned from
                          create_disk_from_image.  Ex. VOptMedia, VDisk, LU,
                          or PV.
        :param stg_ftsk: The pypowervm transaction FeedTask for the
                         I/O Operations. The Virtual I/O Server mapping updates
                         will be added to the FeedTask. This defers the updates
                         to some later point in time.
        """
        lpar_uuid = vm.get_pvm_uuid(instance)

        def add_func(vios_w):
            LOG.info("Adding logical volume disk connection to VIOS %(vios)s.",
                     {'vios': vios_w.name}, instance=instance)
            mapping = tsk_map.build_vscsi_mapping(
                self._host_uuid, vios_w, lpar_uuid, disk_info)
            return tsk_map.add_map(vios_w, mapping)

        stg_ftsk.wrapper_tasks[self._vios_uuid].add_functor_subtask(add_func)

    def _get_vg_wrap(self):
        return pvm_stg.VG.get(self._adapter, uuid=self.vg_uuid,
                              parent_type=pvm_vios.VIOS,
                              parent_uuid=self._vios_uuid)
