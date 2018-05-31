# Copyright 2015, 2018 IBM Corp.
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
from pypowervm import exceptions as pvm_exc
from pypowervm.tasks import scsi_mapper as pvm_smap
from taskflow import task
from taskflow.types import failure as task_fail

from nova import exception
from nova.virt import block_device
from nova.virt.powervm import media
from nova.virt.powervm import mgmt

LOG = logging.getLogger(__name__)


class AttachVolume(task.Task):

    """The task to attach a volume to an instance."""

    def __init__(self, vol_drv):
        """Create the task.

        :param vol_drv: The volume driver. Ties the storage to a connection
                        type (ex. vSCSI).
        """
        self.vol_drv = vol_drv
        self.vol_id = block_device.get_volume_id(self.vol_drv.connection_info)

        super(AttachVolume, self).__init__(name='attach_vol_%s' % self.vol_id)

    def execute(self):
        LOG.info('Attaching volume %(vol)s.', {'vol': self.vol_id},
                 instance=self.vol_drv.instance)
        self.vol_drv.attach_volume()

    def revert(self, result, flow_failures):
        LOG.warning('Rolling back attachment for volume %(vol)s.',
                    {'vol': self.vol_id}, instance=self.vol_drv.instance)

        # Note that the rollback is *instant*.  Resetting the FeedTask ensures
        # immediate rollback.
        self.vol_drv.reset_stg_ftsk()
        try:
            # We attempt to detach in case we 'partially attached'.  In
            # the attach scenario, perhaps one of the Virtual I/O Servers
            # was attached.  This attempts to clear anything out to make sure
            # the terminate attachment runs smoothly.
            self.vol_drv.detach_volume()
        except exception.VolumeDetachFailed:
            # Does not block due to being in the revert flow.
            LOG.exception("Unable to detach volume %s during rollback.",
                          self.vol_id, instance=self.vol_drv.instance)


class DetachVolume(task.Task):

    """The task to detach a volume from an instance."""

    def __init__(self, vol_drv):
        """Create the task.

        :param vol_drv: The volume driver. Ties the storage to a connection
                        type (ex. vSCSI).
        """
        self.vol_drv = vol_drv
        self.vol_id = self.vol_drv.connection_info['data']['volume_id']

        super(DetachVolume, self).__init__(name='detach_vol_%s' % self.vol_id)

    def execute(self):
        LOG.info('Detaching volume %(vol)s.',
                 {'vol': self.vol_id}, instance=self.vol_drv.instance)
        self.vol_drv.detach_volume()

    def revert(self, result, flow_failures):
        LOG.warning('Reattaching volume %(vol)s on detach rollback.',
                    {'vol': self.vol_id}, instance=self.vol_drv.instance)

        # Note that the rollback is *instant*.  Resetting the FeedTask ensures
        # immediate rollback.
        self.vol_drv.reset_stg_ftsk()
        try:
            # We try to reattach the volume here so that it maintains its
            # linkage (in the hypervisor) to the VM.  This makes it easier for
            # operators to understand the linkage between the VMs and volumes
            # in error scenarios.  This is simply useful for debug purposes
            # if there is an operational error.
            self.vol_drv.attach_volume()
        except exception.VolumeAttachFailed:
            # Does not block due to being in the revert flow. See above.
            LOG.exception("Unable to reattach volume %s during rollback.",
                self.vol_id, instance=self.vol_drv.instance)


class CreateDiskForImg(task.Task):

    """The Task to create the disk from an image in the storage."""

    def __init__(self, disk_dvr, context, instance, image_meta):
        """Create the Task.

        Provides the 'disk_dev_info' for other tasks.  Comes from the disk_dvr
        create_disk_from_image method.

        :param disk_dvr: The storage driver.
        :param context: The context passed into the driver method.
        :param instance: The nova instance.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        """
        super(CreateDiskForImg, self).__init__(
            name='create_disk_from_img', provides='disk_dev_info')
        self.disk_dvr = disk_dvr
        self.instance = instance
        self.context = context
        self.image_meta = image_meta

    def execute(self):
        return self.disk_dvr.create_disk_from_image(
            self.context, self.instance, self.image_meta)

    def revert(self, result, flow_failures):
        # If there is no result, or its a direct failure, then there isn't
        # anything to delete.
        if result is None or isinstance(result, task_fail.Failure):
            return

        # Run the delete.  The result is a single disk.  Wrap into list
        # as the method works with plural disks.
        try:
            self.disk_dvr.delete_disks([result])
        except pvm_exc.Error:
            # Don't allow revert exceptions to interrupt the revert flow.
            LOG.exception("Disk deletion failed during revert. Ignoring.",
                          instance=self.instance)


class AttachDisk(task.Task):

    """The task to attach the disk to the instance."""

    def __init__(self, disk_dvr, instance, stg_ftsk):
        """Create the Task for the attach disk to instance method.

        Requires disk info through requirement of disk_dev_info (provided by
        crt_disk_from_img)

        :param disk_dvr: The disk driver.
        :param instance: The nova instance.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        """
        super(AttachDisk, self).__init__(
            name='attach_disk', requires=['disk_dev_info'])
        self.disk_dvr = disk_dvr
        self.instance = instance
        self.stg_ftsk = stg_ftsk

    def execute(self, disk_dev_info):
        self.disk_dvr.attach_disk(self.instance, disk_dev_info, self.stg_ftsk)

    def revert(self, disk_dev_info, result, flow_failures):
        try:
            self.disk_dvr.detach_disk(self.instance)
        except pvm_exc.Error:
            # Don't allow revert exceptions to interrupt the revert flow.
            LOG.exception("Disk detach failed during revert. Ignoring.",
                          instance=self.instance)


class DetachDisk(task.Task):

    """The task to detach the disk storage from the instance."""

    def __init__(self, disk_dvr, instance):
        """Creates the Task to detach the storage adapters.

        Provides the stor_adpt_mappings.  A list of pypowervm
        VSCSIMappings or VFCMappings (depending on the storage adapter).

        :param disk_dvr: The DiskAdapter for the VM.
        :param instance: The nova instance.
        """
        super(DetachDisk, self).__init__(
            name='detach_disk', provides='stor_adpt_mappings')
        self.instance = instance
        self.disk_dvr = disk_dvr

    def execute(self):
        return self.disk_dvr.detach_disk(self.instance)


class DeleteDisk(task.Task):

    """The task to delete the backing storage."""

    def __init__(self, disk_dvr):
        """Creates the Task to delete the disk storage from the system.

        Requires the stor_adpt_mappings.

        :param disk_dvr: The DiskAdapter for the VM.
        """
        super(DeleteDisk, self).__init__(
            name='delete_disk', requires=['stor_adpt_mappings'])
        self.disk_dvr = disk_dvr

    def execute(self, stor_adpt_mappings):
        self.disk_dvr.delete_disks(stor_adpt_mappings)


class CreateAndConnectCfgDrive(task.Task):

    """The task to create the configuration drive."""

    def __init__(self, adapter, instance, injected_files,
                 network_info, stg_ftsk, admin_pass=None):
        """Create the Task that creates and connects the config drive.

        Requires the 'mgmt_cna'

        :param adapter: The adapter for the pypowervm API
        :param instance: The nova instance
        :param injected_files: A list of file paths that will be injected into
                               the ISO.
        :param network_info: The network_info from the nova spawn method.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        :param admin_pass (Optional, Default None): Password to inject for the
                                                    VM.
        """
        super(CreateAndConnectCfgDrive, self).__init__(
            name='cfg_drive', requires=['mgmt_cna'])
        self.adapter = adapter
        self.instance = instance
        self.injected_files = injected_files
        self.network_info = network_info
        self.stg_ftsk = stg_ftsk
        self.ad_pass = admin_pass
        self.mb = None

    def execute(self, mgmt_cna):
        self.mb = media.ConfigDrivePowerVM(self.adapter)
        self.mb.create_cfg_drv_vopt(self.instance, self.injected_files,
                                    self.network_info, self.stg_ftsk,
                                    admin_pass=self.ad_pass, mgmt_cna=mgmt_cna)

    def revert(self, mgmt_cna, result, flow_failures):
        # No media builder, nothing to do
        if self.mb is None:
            return

        # Delete the virtual optical media. We don't care if it fails
        try:
            self.mb.dlt_vopt(self.instance, self.stg_ftsk)
        except pvm_exc.Error:
            LOG.exception('VOpt removal (as part of reversion) failed.',
                instance=self.instance)


class DeleteVOpt(task.Task):

    """The task to delete the virtual optical."""

    def __init__(self, adapter, instance, stg_ftsk=None):
        """Creates the Task to delete the instance's virtual optical media.

        :param adapter: The adapter for the pypowervm API
        :param instance: The nova instance.
        :param stg_ftsk: FeedTask to defer storage connectivity operations.
        """
        super(DeleteVOpt, self).__init__(name='vopt_delete')
        self.adapter = adapter
        self.instance = instance
        self.stg_ftsk = stg_ftsk

    def execute(self):
        media_builder = media.ConfigDrivePowerVM(self.adapter)
        media_builder.dlt_vopt(self.instance, stg_ftsk=self.stg_ftsk)


class InstanceDiskToMgmt(task.Task):

    """The task to connect an instance's disk to the management partition.

    This task will connect the instance's disk to the management partition and
    discover it. We do these two pieces together because their reversion
    happens in the same order.
    """

    def __init__(self, disk_dvr, instance):
        """Create the Task for connecting boot disk to mgmt partition.

        Provides:
        stg_elem: The storage element wrapper (pypowervm LU, PV, etc.) that was
                  connected.
        vios_wrap: The Virtual I/O Server wrapper from which the storage
                   element was mapped.
        disk_path: The local path to the mapped-and-discovered device, e.g.
                   '/dev/sde'.

        :param disk_dvr: The disk driver.
        :param instance: The nova instance whose boot disk is to be connected.
        """
        super(InstanceDiskToMgmt, self).__init__(
            name='instance_disk_to_mgmt',
            provides=['stg_elem', 'vios_wrap', 'disk_path'])
        self.disk_dvr = disk_dvr
        self.instance = instance
        self.stg_elem = None
        self.vios_wrap = None
        self.disk_path = None

    def execute(self):
        """Map the instance's boot disk and discover it."""

        # Search for boot disk on the NovaLink partition.
        if self.disk_dvr.mp_uuid in self.disk_dvr._vios_uuids:
            dev_name = self.disk_dvr.get_bootdisk_path(
                self.instance, self.disk_dvr.mp_uuid)
            if dev_name is not None:
                return None, None, dev_name

        self.stg_elem, self.vios_wrap = (
            self.disk_dvr.connect_instance_disk_to_mgmt(self.instance))
        new_maps = pvm_smap.find_maps(
            self.vios_wrap.scsi_mappings, client_lpar_id=self.disk_dvr.mp_uuid,
            stg_elem=self.stg_elem)
        if not new_maps:
            raise exception.NewMgmtMappingNotFoundException(
                stg_name=self.stg_elem.name, vios_name=self.vios_wrap.name)

        # new_maps should be length 1, but even if it's not - i.e. we somehow
        # matched more than one mapping of the same dev to the management
        # partition from the same VIOS - it is safe to use the first one.
        mapping = new_maps[0]
        # Scan the SCSI bus, discover the disk, find its canonical path.
        LOG.info("Discovering device and path for mapping of %(dev_name)s "
                 "on the management partition.",
                 {'dev_name': self.stg_elem.name}, instance=self.instance)
        self.disk_path = mgmt.discover_vscsi_disk(mapping)
        return self.stg_elem, self.vios_wrap, self.disk_path

    def revert(self, result, flow_failures):
        """Unmap the disk and then remove it from the management partition.

        We use this order to avoid rediscovering the device in case some other
        thread scans the SCSI bus between when we remove and when we unmap.
        """
        if self.vios_wrap is None or self.stg_elem is None:
            # We never even got connected - nothing to do.
            return
        LOG.warning("Unmapping boot disk %(disk_name)s from the management "
                    "partition via Virtual I/O Server %(vioname)s.",
                    {'disk_name': self.stg_elem.name,
                     'vioname': self.vios_wrap.name}, instance=self.instance)
        self.disk_dvr.disconnect_disk_from_mgmt(self.vios_wrap.uuid,
                                                self.stg_elem.name)

        if self.disk_path is None:
            # We did not discover the disk - nothing else to do.
            return
        LOG.warning("Removing disk %(dpath)s from the management partition.",
                    {'dpath': self.disk_path}, instance=self.instance)
        try:
            mgmt.remove_block_dev(self.disk_path)
        except pvm_exc.Error:
            # Don't allow revert exceptions to interrupt the revert flow.
            LOG.exception("Remove disk failed during revert. Ignoring.",
                          instance=self.instance)


class RemoveInstanceDiskFromMgmt(task.Task):

    """Unmap and remove an instance's boot disk from the mgmt partition."""

    def __init__(self, disk_dvr, instance):
        """Create task to unmap and remove an instance's boot disk from mgmt.

        Requires (from InstanceDiskToMgmt):
        stg_elem: The storage element wrapper (pypowervm LU, PV, etc.) that was
                  connected.
        vios_wrap: The Virtual I/O Server wrapper.
                   (pypowervm.wrappers.virtual_io_server.VIOS) from which the
                   storage element was mapped.
        disk_path: The local path to the mapped-and-discovered device, e.g.
                   '/dev/sde'.
        :param disk_dvr: The disk driver.
        :param instance: The nova instance whose boot disk is to be connected.
        """
        self.disk_dvr = disk_dvr
        self.instance = instance
        super(RemoveInstanceDiskFromMgmt, self).__init__(
            name='remove_inst_disk_from_mgmt',
            requires=['stg_elem', 'vios_wrap', 'disk_path'])

    def execute(self, stg_elem, vios_wrap, disk_path):
        """Unmap and remove an instance's boot disk from the mgmt partition.

        Input parameters ('requires') provided by InstanceDiskToMgmt task.
        :param stg_elem: The storage element wrapper (pypowervm LU, PV, etc.)
                         to be disconnected.
        :param vios_wrap: The Virtual I/O Server wrapper from which the
                          mapping is to be removed.
        :param disk_path: The local path to the disk device to be removed, e.g.
                          '/dev/sde'
        """
        # stg_elem is None if boot disk was not mapped to management partition.
        if stg_elem is None:
            return
        LOG.info("Unmapping boot disk %(disk_name)s from the management "
                 "partition via Virtual I/O Server %(vios_name)s.",
                 {'disk_name': stg_elem.name, 'vios_name': vios_wrap.name},
                 instance=self.instance)
        self.disk_dvr.disconnect_disk_from_mgmt(vios_wrap.uuid, stg_elem.name)
        LOG.info("Removing disk %(disk_path)s from the management partition.",
                 {'disk_path': disk_path}, instance=self.instance)
        mgmt.remove_block_dev(disk_path)
