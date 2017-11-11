# Copyright 2013 OpenStack Foundation
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

import nova.privsep.fs
from nova import test


class PrivsepFilesystemHelpersTestCase(test.NoDBTestCase):
    @mock.patch('oslo_concurrency.processutils.execute')
    def test_list_partitions(self, mock_execute):
        parted_return = "BYT;\n...\n"
        parted_return += "1:2s:11s:10s:ext3::boot;\n"
        parted_return += "2:20s:11s:10s::bob:;\n"
        mock_execute.return_value = (parted_return, None)

        partitions = nova.privsep.fs.unprivileged_list_partitions("abc")

        self.assertEqual(2, len(partitions))
        self.assertEqual((1, 2, 10, "ext3", "", "boot"), partitions[0])
        self.assertEqual((2, 20, 10, "", "bob", ""), partitions[1])
