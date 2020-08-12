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

from lxml import etree
from urllib import parse as urlparse

from nova import context
from nova.network import constants as neutron_constants
from nova.network import neutron
from nova.tests.functional.libvirt import base as libvirt_base
from nova.tests.unit.virt.libvirt import fake_os_brick_connector
from nova.tests.unit.virt.libvirt import fakelibvirt


class TestLiveMigrationWithoutMultiplePortBindings(
        libvirt_base.ServersTestBase):
    """Regression test for bug 1888395.

    This regression test asserts that Live migration works when
    neutron does not support the binding-extended api extension
    and the legacy single port binding workflow is used.
    """

    ADMIN_API = True
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
        super().setUp()
        self.neutron.list_extensions = self.list_extensions
        self.neutron_api = neutron.API()
        # TODO(sean-k-mooney): remove after
        # I275509eb0e0eb9eaf26fe607b7d9a67e1edc71f8
        # has merged.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.connector',
            fake_os_brick_connector))

        self.start_compute(
            hostname='start_host',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=2,
                kB_mem=10740000))
        self.start_compute(
            hostname='end_host',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=2,
                kB_mem=10740000))

        self.ctxt = context.get_admin_context()
        # TODO(sean-k-mooney): remove this when it is part of ServersTestBase
        self.useFixture(fixtures.MonkeyPatch(
            'nova.tests.unit.virt.libvirt.fakelibvirt.Domain.migrateToURI3',
            self._migrate_stub))

    def _migrate_stub(self, domain, destination, params, flags):
        """Stub out migrateToURI3."""

        src_hostname = domain._connection.hostname
        dst_hostname = urlparse.urlparse(destination).netloc

        # In a real live migration, libvirt and QEMU on the source and
        # destination talk it out, resulting in the instance starting to exist
        # on the destination. Fakelibvirt cannot do that, so we have to
        # manually create the "incoming" instance on the destination
        # fakelibvirt.
        dst = self.computes[dst_hostname]
        dst.driver._host.get_connection().createXML(
            params['destination_xml'],
            'fake-createXML-doesnt-care-about-flags')

        src = self.computes[src_hostname]
        conn = src.driver._host.get_connection()

        # because migrateToURI3 is spawned in a background thread, this method
        # does not block the upper nova layers. Because we don't want nova to
        # think the live migration has finished until this method is done, the
        # last thing we do is make fakelibvirt's Domain.jobStats() return
        # VIR_DOMAIN_JOB_COMPLETED.
        server = etree.fromstring(
            params['destination_xml']
        ).find('./uuid').text
        dom = conn.lookupByUUIDString(server)
        dom.complete_job()

    def test_live_migrate(self):
        server = self._create_server(
            host='start_host',
            networks=[{'port': self.neutron.port_1['id']}])

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

        self._wait_for_server_parameter(
            server, {'OS-EXT-SRV-ATTR:host': 'end_host', 'status': 'ACTIVE'})
        msg = "NotImplementedError: Cannot load 'vif_type' in the base class"
        self.assertNotIn(msg, self.stdlog.logger.output)
