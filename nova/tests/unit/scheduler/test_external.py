# Copyright 2025 SAP SE or an SAP affiliate company.
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

# Tests for external scheduler api.

from unittest.mock import MagicMock
from unittest.mock import patch
from unittest.mock import sentinel

import requests

from nova import objects
from nova.scheduler.external import call_external_scheduler_api
from nova import test
from nova.tests.unit.scheduler import fakes


class ExternalSchedulerAPITestCase(test.NoDBTestCase):
    def setUp(self):
        super(ExternalSchedulerAPITestCase, self).setUp()
        self.flags(
            external_scheduler_api_url='http://127.0.0.1:1234',
            group='filter_scheduler'
        )
        self.example_hosts = [
            fakes.FakeHostState('host1', 'node1', {'status': 'up'}),
            fakes.FakeHostState('host2', 'node2', {'status': 'up'}),
            fakes.FakeHostState('host3', 'node3', {'status': 'down'})
        ]
        self.example_weights = {
            'host1': 1.0,
            'host2': 0.5,
            'host3': 0.0,
        }
        self.example_spec = objects.RequestSpec(
            context=sentinel.ctx,
            flavor=objects.Flavor(
                name='small',
                vcpus=4,
                memory_mb=1024,
                extra_specs={},
            ),
        )

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.debug')
    def test_enabled_api_success(self, mock_debug_log, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'hosts': ['host1', 'host3']}
        mock_post.return_value = mock_response

        log = ""

        def append_log(msg, data):
            nonlocal log
            log += msg % data
        mock_debug_log.side_effect = append_log

        hosts = call_external_scheduler_api(
            self.example_hosts,
            self.example_weights,
            self.example_spec,
        )
        self.assertEqual(
            ['host1', 'host3'],
            [h.host for h in hosts]
        )
        self.assertIn('Calling external scheduler API with ', log)

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.warning')
    def test_enabled_api_empty_response(self, mock_warn_log, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'hosts': []}
        mock_post.return_value = mock_response

        hosts = call_external_scheduler_api(
            self.example_hosts,
            self.example_weights,
            self.example_spec,
        )
        self.assertEqual([], hosts)
        mock_warn_log.assert_called_with(
            'External scheduler filtered out all hosts.'
        )

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.error')
    def test_enabled_api_timeout(self, mock_err_log, mock_post):
        mock_post.side_effect = requests.exceptions.Timeout

        log = ""

        def append_log(msg, data):
            nonlocal log
            log += msg % data
        mock_err_log.side_effect = append_log

        hosts = call_external_scheduler_api(
            self.example_hosts,
            self.example_weights,
            self.example_spec,
        )
        # Should fallback to the original host list.
        self.assertEqual(
            ['host1', 'host2', 'host3'],
            [h.host for h in hosts]
        )
        self.assertIn('Failed to call external scheduler API: ', log)

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.error')
    def test_enabled_api_invalid_response(self, mock_err_log, mock_post):
        invalid_response_dicts = [
            {},
            {"hosts": "not a list"},
            {"hosts": [1, 2, "host1"]},
            {"hosts": [{"name": "host1", "status": "up"}]},
        ]

        log = ""

        def append_log(msg, data):
            nonlocal log
            log += msg % data
        mock_err_log.side_effect = append_log

        for response_dict in invalid_response_dicts:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = response_dict
            mock_post.return_value = mock_response

            hosts = call_external_scheduler_api(
                self.example_hosts,
                self.example_weights,
                self.example_spec,
            )
            # Should fallback to the original host list.
            self.assertEqual(
                ['host1', 'host2', 'host3'],
                [h.host for h in hosts]
            )
            self.assertIn('External scheduler response is invalid: ', log)

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.error')
    def test_enabled_api_request_exceptions(self, mock_err_log, mock_post):
        """Test that request exceptions are caught and logged."""
        tests = [
            # Simulate a http error during request fetch.
            (400, requests.exceptions.HTTPError),
            # Simulate a parsing error after the fetch has happened.
            (200, requests.exceptions.InvalidJSONError),
        ]

        for status_code, request_exception in tests:
            log = ""

            def append_log(msg, data):
                nonlocal log
                log += msg % data
            mock_err_log.side_effect = append_log

            mock_response = MagicMock()
            mock_response.status_code = status_code
            mock_response.json.side_effect = request_exception
            mock_post.return_value = mock_response

            hosts = call_external_scheduler_api(
                self.example_hosts,
                self.example_weights,
                self.example_spec,
            )
            # Should fallback to the original host list.
            self.assertEqual(
                ['host1', 'host2', 'host3'],
                [h.host for h in hosts]
            )
            self.assertIn('Failed to call external scheduler API: ', log)

    @patch('requests.post')
    @patch('nova.scheduler.external.LOG.error')
    def test_enabled_api_error_reply(self, mock_err_log, mock_post):
        mock_post.side_effect = requests.exceptions.HTTPError

        log = ""

        def append_log(msg, data):
            nonlocal log
            log += msg % data
        mock_err_log.side_effect = append_log

        hosts = call_external_scheduler_api(
            self.example_hosts,
            self.example_weights,
            self.example_spec,
        )
        # Should fallback to the original host list.
        self.assertEqual(
            ['host1', 'host2', 'host3'],
            [h.host for h in hosts]
        )
        self.assertIn('Failed to call external scheduler API: ', log)
