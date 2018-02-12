# Copyright 2015, 2017 IBM Corp.
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
from taskflow import task
from taskflow.types import failure as task_fail

from nova.virt.powervm import media

LOG = logging.getLogger(__name__)


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
