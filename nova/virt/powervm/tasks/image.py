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

from oslo_log import log as logging
from taskflow import task

from nova.virt.powervm import image


LOG = logging.getLogger(__name__)


class UpdateTaskState(task.Task):

    def __init__(self, update_task_state, task_state, expected_state=None):
        """Invoke the update_task_state callback with the desired arguments.

        :param update_task_state: update_task_state callable passed into
                                  snapshot.
        :param task_state: The new task state (from nova.compute.task_states)
                           to set.
        :param expected_state: Optional. The expected state of the task prior
                               to this request.
        """
        self.update_task_state = update_task_state
        self.task_state = task_state
        self.kwargs = {}
        if expected_state is not None:
            # We only want to pass expected state if it's not None! That's so
            # we take the update_task_state method's default.
            self.kwargs['expected_state'] = expected_state
        super(UpdateTaskState, self).__init__(
            name='update_task_state_%s' % task_state)

    def execute(self):
        self.update_task_state(self.task_state, **self.kwargs)


class StreamToGlance(task.Task):

    """Task around streaming a block device to glance."""

    def __init__(self, context, image_api, image_id, instance):
        """Initialize the flow for streaming a block device to glance.

        Requires: disk_path: Path to the block device file for the instance's
                             boot disk.
        :param context: Nova security context.
        :param image_api: Handle to the glance API.
        :param image_id: UUID of the prepared glance image.
        :param instance: Instance whose backing device is being captured.
        """
        self.context = context
        self.image_api = image_api
        self.image_id = image_id
        self.instance = instance
        super(StreamToGlance, self).__init__(name='stream_to_glance',
                                             requires='disk_path')

    def execute(self, disk_path):
        metadata = image.generate_snapshot_metadata(
            self.context, self.image_api, self.image_id, self.instance)
        LOG.info("Starting stream of boot device (local blockdev %(devpath)s) "
                 "to glance image %(img_id)s.",
                 {'devpath': disk_path, 'img_id': self.image_id},
                 instance=self.instance)
        image.stream_blockdev_to_glance(self.context, self.image_api,
                                        self.image_id, metadata, disk_path)
