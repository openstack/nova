# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import mock

from nova.cmd import scheduler
from nova import config
from nova import test


# required because otherwise oslo early parse_args dies
@mock.patch.object(config, 'parse_args', new=lambda *args, **kwargs: None)
class TestScheduler(test.NoDBTestCase):

    @mock.patch('nova.service.Service.create')
    @mock.patch('nova.service.serve')
    @mock.patch('nova.service.wait')
    @mock.patch('oslo_concurrency.processutils.get_worker_count',
                return_value=2)
    def test_workers_defaults(self, get_worker_count, mock_wait, mock_serve,
                              service_create):
        scheduler.main()
        get_worker_count.assert_called_once_with()
        mock_serve.assert_called_once_with(
            service_create.return_value, workers=2)
        mock_wait.assert_called_once_with()

    @mock.patch('nova.service.Service.create')
    @mock.patch('nova.service.serve')
    @mock.patch('nova.service.wait')
    @mock.patch('oslo_concurrency.processutils.get_worker_count')
    def test_workers_override(self, get_worker_count, mock_wait, mock_serve,
                              service_create):
        self.flags(workers=4, group='scheduler')
        scheduler.main()
        get_worker_count.assert_not_called()
        mock_serve.assert_called_once_with(
            service_create.return_value, workers=4)
        mock_wait.assert_called_once_with()

    @mock.patch('nova.service.Service.create')
    @mock.patch('nova.service.serve')
    @mock.patch('nova.service.wait')
    @mock.patch('oslo_concurrency.processutils.get_worker_count')
    def test_workers_caching_scheduler(self, get_worker_count, mock_wait,
                                       mock_serve, service_create):
        self.flags(driver='caching_scheduler', group='scheduler')
        scheduler.main()
        get_worker_count.assert_not_called()
        mock_serve.assert_called_once_with(
            service_create.return_value, workers=1)
        mock_wait.assert_called_once_with()
