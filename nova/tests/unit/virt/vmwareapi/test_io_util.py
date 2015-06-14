# Copyright (c) 2014 VMware, Inc.
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

from nova import exception
from nova import test
from nova.virt.vmwareapi import io_util


@mock.patch.object(io_util, 'IMAGE_API')
class GlanceWriteThreadTestCase(test.NoDBTestCase):

    def test_start_image_update_service_exception(self, mocked):
        mocked.update.side_effect = exception.ImageNotAuthorized(
            image_id='image')
        write_thread = io_util.GlanceWriteThread(
            None, None, image_id=None)
        write_thread.start()
        self.assertRaises(exception.ImageNotAuthorized, write_thread.wait)
        write_thread.stop()
        write_thread.close()
