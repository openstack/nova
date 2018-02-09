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

import mock

from nova import test

from nova.virt.powervm.tasks import image as tsk_img


class TestImage(test.TestCase):
    def test_update_task_state(self):
        def func(task_state, expected_state='delirious'):
            self.assertEqual('task_state', task_state)
            self.assertEqual('delirious', expected_state)
        tf = tsk_img.UpdateTaskState(func, 'task_state')
        self.assertEqual('update_task_state_task_state', tf.name)
        tf.execute()

        def func2(task_state, expected_state=None):
            self.assertEqual('task_state', task_state)
            self.assertEqual('expected_state', expected_state)
        tf = tsk_img.UpdateTaskState(func2, 'task_state',
                                     expected_state='expected_state')
        tf.execute()

        # Validate args on taskflow.task.Task instantiation
        with mock.patch('taskflow.task.Task.__init__') as tf:
            tsk_img.UpdateTaskState(func, 'task_state')
        tf.assert_called_once_with(
            name='update_task_state_task_state')

    @mock.patch('nova.virt.powervm.image.stream_blockdev_to_glance',
                autospec=True)
    @mock.patch('nova.virt.powervm.image.generate_snapshot_metadata',
                autospec=True)
    def test_stream_to_glance(self, mock_metadata, mock_stream):
        mock_metadata.return_value = 'metadata'
        mock_inst = mock.Mock()
        mock_inst.name = 'instance_name'
        tf = tsk_img.StreamToGlance('context', 'image_api', 'image_id',
                                    mock_inst)
        self.assertEqual('stream_to_glance', tf.name)
        tf.execute('disk_path')
        mock_metadata.assert_called_with('context', 'image_api', 'image_id',
                                         mock_inst)
        mock_stream.assert_called_with('context', 'image_api', 'image_id',
                                       'metadata', 'disk_path')

        # Validate args on taskflow.task.Task instantiation
        with mock.patch('taskflow.task.Task.__init__') as tf:
            tsk_img.StreamToGlance(
                'context', 'image_api', 'image_id', mock_inst)
        tf.assert_called_once_with(
            name='stream_to_glance', requires='disk_path')
