# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import mock

from nova.cmd import manage
from nova import objects
from nova import test


class ServiceCommandsTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ServiceCommandsTestCase, self).setUp()
        self.svc_cmds = manage.ServiceCommands()

    @mock.patch('nova.db.instance_get_all_by_host')
    @mock.patch.object(objects.ComputeNode,
                       'get_first_node_by_host_for_old_compat')
    def test__show_host_resources(self, mock_cn_get, mock_inst_get):
        resources = {'vcpus': 4,
                     'memory_mb': 65536,
                     'local_gb': 100,
                     'vcpus_used': 1,
                     'memory_mb_used': 16384,
                     'local_gb_used': 20}
        mock_cn_get.return_value = objects.ComputeNode(**resources)
        mock_inst_get.return_value = []

        result = self.svc_cmds._show_host_resources(mock.sentinel.ctxt,
                                                    mock.sentinel.host)

        mock_cn_get.assert_called_once_with(mock.sentinel.ctxt,
                                            mock.sentinel.host)
        mock_inst_get.assert_called_once_with(mock.sentinel.ctxt,
                                              mock.sentinel.host)
        self.assertEqual(resources, result['resource'])
        self.assertEqual({}, result['usage'])
