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
            'create_disk_from_img', provides='disk_dev_info')
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
            'attach_disk', requires=['disk_dev_info'])
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
            'detach_disk', provides='stor_adpt_mappings')
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
            'delete_disk', requires=['stor_adpt_mappings'])
        self.disk_dvr = disk_dvr

    def execute(self, stor_adpt_mappings):
        self.disk_dvr.delete_disks(stor_adpt_mappings)
