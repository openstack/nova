# Copyright 2021, Red Hat, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers


class TestMigrateFromDownHost(integrated_helpers._IntegratedTestBase):
    """Regression test for bug #1938326

    Assert the behaviour of n-api when requests are made to migrate an instance
    from a disabled, forced down, down and disabled and down compute
    host.

    Bug #1938326 specifically covering the case where a request is made and
    accepted to migrate an instance from a disabled and down compute host.
    """
    microversion = 'latest'
    ADMIN_API = True

    def _setup_compute_service(self):
        # We want the service to be marked down in a reasonable time while
        # ensuring we don't accidentally mark services as down prematurely
        self.flags(report_interval=1)
        self.flags(service_down_time=6)

        # Use two compute services to make it easier to assert the call from
        # the dest to the src, we could also test this for same host resize.
        self._start_compute('src')
        self._start_compute('dest')

    def test_migrate_from_disabled_host(self):
        """Assert that migration requests for disabled hosts are allowed
        """
        # Launch an instance on src
        server = self._create_server(host='src', networks='none')

        # Mark the compute service as disabled
        source_compute_id = self.api.get_services(
            host='src', binary='nova-compute')[0]['id']
        self.api.put_service(source_compute_id, {"status": "disabled"})
        self._wait_for_service_parameter(
            'src', 'nova-compute',
            {
                'status': 'disabled',
                'state': 'up'
            }
        )

        # Assert that we can migrate and confirm from a disabled but up compute
        self._migrate_server(server)
        self._confirm_resize(server)

    def test_migrate_from_forced_down_host(self):
        """Assert that migration requests for forced down hosts are rejected
        """
        # Launch an instance on src
        server = self._create_server(host='src', networks='none')

        # Force down the compute
        source_compute_id = self.api.get_services(
            host='src', binary='nova-compute')[0]['id']
        self.api.put_service(source_compute_id, {'forced_down': 'true'})
        # NOTE(gibi): extra retries are needed as the default 10 retries with
        # 0.5 second sleep is close to the 6 seconds down timeout
        self._wait_for_service_parameter(
            'src', 'nova-compute',
            {
                'forced_down': True,
                'state': 'down',
                'status': 'enabled'
            },
            max_retries=20,
        )

        # Assert that we cannot migrate from a forced down compute
        ex = self.assertRaises(
            client.OpenStackApiException, self._migrate_server, server)
        self.assertEqual(409, ex.response.status_code)

    def test_migrate_from_down_host(self):
        """Assert that migration requests from down hosts are rejected
        """
        # Launch an instance on src
        server = self._create_server(host='src', networks='none')

        # Stop the compute service and wait until it's down
        self.computes['src'].stop()
        # NOTE(gibi): extra retries are needed as the default 10 retries with
        # 0.5 second sleep is close to the 6 seconds down timeout
        self._wait_for_service_parameter(
            'src', 'nova-compute',
            {
                'state': 'down',
                'status': 'enabled'
            },
            max_retries=20,
        )

        # Assert that requests to migrate from down computes are rejected
        ex = self.assertRaises(
            client.OpenStackApiException, self.api.post_server_action,
            server['id'], {'migrate': None})
        self.assertEqual(409, ex.response.status_code)

    def test_migrate_from_disabled_down_host(self):
        """Assert that migration requests for disabled down hosts are rejected
        """
        # Launch an instance on src
        server = self._create_server(host='src', networks='none')

        # Mark the compute service as disabled
        source_compute_id = self.api.get_services(
            host='src', binary='nova-compute')[0]['id']
        self.api.put_service(source_compute_id, {"status": "disabled"})
        self._wait_for_service_parameter(
            'src', 'nova-compute', {'status': 'disabled'})

        # Stop the compute service and wait until it's down
        self.computes['src'].stop()
        # NOTE(gibi): extra retries are needed as the default 10 retries with
        # 0.5 second sleep is close to the 6 seconds down timeout
        self._wait_for_service_parameter(
            'src', 'nova-compute', {'state': 'down'}, max_retries=20)

        ex = self.assertRaises(
            client.OpenStackApiException, self.api.post_server_action,
            server['id'], {'migrate': None})
        self.assertEqual(409, ex.response.status_code)
