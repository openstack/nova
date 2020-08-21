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

import fixtures
import mock

from nova import context
from nova.network.neutronv2 import api as neutron
from nova.network.neutronv2 import constants as neutron_constants
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base as libvirt_base
from nova.tests.unit.virt.libvirt import fake_os_brick_connector
from nova.tests.unit.virt.libvirt import fakelibvirt


class TestLiveMigrationWithoutMultiplePortBindings(
        integrated_helpers.InstanceHelperMixin,
        libvirt_base.ServersTestBase):
    """Regression test for bug 1888395.

    This regression test asserts that Live migration works when
    neutron does not support the binding-extended api extension
    and the legacy single port binding workflow is used.
    """

    ADMIN_API = True
    api_major_version = 'v2.1'
    microversion = 'latest'

    def list_extensions(self, *args, **kwargs):
        return {
            'extensions': [
                {
                    # Copied from neutron-lib portbindings.py
                    "updated": "2014-02-03T10:00:00-00:00",
                    "name": neutron_constants.PORT_BINDING,
                    "links": [],
                    "alias": "binding",
                    "description": "Expose port bindings of a virtual port to "
                                   "external application"
                }
            ]
        }

    def setUp(self):
        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)
        super(TestLiveMigrationWithoutMultiplePortBindings, self).setUp()
        self.neutron.list_extensions = self.list_extensions
        self.neutron_api = neutron.API()
        # TODO(sean-k-mooney): remove after
        # I275509eb0e0eb9eaf26fe607b7d9a67e1edc71f8
        # has merged.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.connector',
            fake_os_brick_connector))

        self.computes = {}
        for host in ['start_host', 'end_host']:
            host_info = fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=2,
                kB_mem=10740000)
            fake_connection = self._get_connection(
                host_info=host_info, hostname=host)

            # This is fun. Firstly we need to do a global'ish mock so we can
            # actually start the service.
            with mock.patch('nova.virt.libvirt.host.Host.get_connection',
                            return_value=fake_connection):
                compute = self.start_service('compute', host=host)

            # Once that's done, we need to do some tweaks to each individual
            # compute "service" to make sure they return unique objects
            compute.driver._host.get_connection = lambda: fake_connection
            self.computes[host] = compute

        self.ctxt = context.get_admin_context()

    def test_live_migrate(self):
        flavors = self.api.get_flavors()
        flavor = flavors[0]
        server_req = self._build_minimal_create_server_request(
            self.api, 'some-server', flavor_id=flavor['id'],
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks=[{'port': self.neutron.port_1['id']}])
        server_req['availability_zone'] = 'nova:%s' % "start_host"
        created_server = self.api.post_server({'server': server_req})
        server = self._wait_for_state_change(
            self.api, created_server, 'ACTIVE')
        self.assertFalse(
            self.neutron_api.supports_port_binding_extension(self.ctxt))
        # TODO(sean-k-mooney): extend _live_migrate to support passing a host
        self.api.post_server_action(
            server['id'],
            {
                'os-migrateLive': {
                    'host': 'end_host',
                    'block_migration': 'auto'
                }
            }
        )

        # FIXME(sean-k-mooney): this should succeed but because of bug #188395
        # it will fail.
        # self._wait_for_server_parameter(
        #     server, {'OS-EXT-SRV-ATTR:host': 'end_host', 'status': 'ACTIVE'})
        # because of the bug the migration will fail in pre_live_migrate so
        # the vm should still be active on the start_host
        self._wait_for_server_parameter(
            self.api, server,
            {'OS-EXT-SRV-ATTR:host': 'start_host', 'status': 'ACTIVE'})

        msg = "NotImplementedError: Cannot load 'vif_type' in the base class"
        self.assertIn(msg, self.stdlog.logger.output)
