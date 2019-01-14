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
import six

from nova import test

from nova.virt.powervm import image


class TestImage(test.TestCase):

    @mock.patch('nova.utils.temporary_chown', autospec=True)
    @mock.patch('nova.image.api.API', autospec=True)
    def test_stream_blockdev_to_glance(self, mock_api, mock_chown):
        mock_open = mock.mock_open()
        with mock.patch.object(six.moves.builtins, 'open', new=mock_open):
            image.stream_blockdev_to_glance('context', mock_api, 'image_id',
                                            'metadata', '/dev/disk')
        mock_chown.assert_called_with('/dev/disk')
        mock_open.assert_called_with('/dev/disk', 'rb')
        mock_api.update.assert_called_with('context', 'image_id', 'metadata',
                                           mock_open.return_value)

    @mock.patch('nova.image.api.API', autospec=True)
    def test_generate_snapshot_metadata(self, mock_api):
        mock_api.get.return_value = {'name': 'image_name'}
        mock_instance = mock.Mock()
        mock_instance.project_id = 'project_id'
        ret = image.generate_snapshot_metadata('context', mock_api, 'image_id',
                                               mock_instance)
        mock_api.get.assert_called_with('context', 'image_id')
        self.assertEqual({
            'name': 'image_name',
            'status': 'active',
            'disk_format': 'raw',
            'container_format': 'bare',
            'properties': {
                'image_location': 'snapshot',
                'image_state': 'available',
                'owner_id': 'project_id',
            }
        }, ret)
