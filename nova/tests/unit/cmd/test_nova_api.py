# Copyright 2015 HPE, Inc.
#
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

from nova.cmd import api
from nova import config
from nova import exception
from nova import test


# required because otherwise oslo early parse_args dies
@mock.patch.object(config, 'parse_args', new=lambda *args, **kwargs: None)
# required so we don't set the global service version cache
@mock.patch('nova.objects.Service.enable_min_version_cache')
class TestNovaAPI(test.NoDBTestCase):

    def test_continues_on_failure(self, version_cache):
        count = [1]

        fake_server = mock.MagicMock()
        fake_server.workers = 123

        def fake_service(api, **kw):
            while count:
                count.pop()
                raise exception.PasteAppNotFound(name=api, path='/')
            return fake_server

        self.flags(enabled_apis=['osapi_compute', 'metadata'])
        with mock.patch.object(api, 'service') as mock_service:
            mock_service.WSGIService.side_effect = fake_service
            api.main()
            mock_service.WSGIService.assert_has_calls([
                mock.call('osapi_compute', use_ssl=False),
                mock.call('metadata', use_ssl=False),
            ])
            launcher = mock_service.process_launcher.return_value
            launcher.launch_service.assert_called_once_with(
                fake_server, workers=123)
        self.assertTrue(version_cache.called)

    @mock.patch('sys.exit')
    def test_fails_if_none_started(self, mock_exit, version_cache):
        mock_exit.side_effect = test.TestingException
        self.flags(enabled_apis=[])
        with mock.patch.object(api, 'service') as mock_service:
            self.assertRaises(test.TestingException, api.main)
            mock_exit.assert_called_once_with(1)
            launcher = mock_service.process_launcher.return_value
            self.assertFalse(launcher.wait.called)
        self.assertFalse(version_cache.called)

    @mock.patch('sys.exit')
    def test_fails_if_all_failed(self, mock_exit, version_cache):
        mock_exit.side_effect = test.TestingException
        self.flags(enabled_apis=['osapi_compute', 'metadata'])
        with mock.patch.object(api, 'service') as mock_service:
            mock_service.WSGIService.side_effect = exception.PasteAppNotFound(
                name='foo', path='/')
            self.assertRaises(test.TestingException, api.main)
            mock_exit.assert_called_once_with(1)
            launcher = mock_service.process_launcher.return_value
            self.assertFalse(launcher.wait.called)
        self.assertTrue(version_cache.called)
