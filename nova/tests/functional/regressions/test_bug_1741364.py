# Copyright (C) 2026 Canonical, Inc.
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

"""Regression test for bug 1741364

When an instance is backed by an rbd ephemeral/root disk, Nova captures
the Ceph monitor addresses returned by rbd_utils.RBDDriver.get_mon_addrs
at instance creation time and embeds them as <host> entries inside the
<disk><source protocol='rbd'> element of the libvirt XML.

If the cluster's monitor addresses subsequently change (for example because
mons are redeployed onto new IPs) and the instance is then live migrated,
nova.virt.libvirt.migration.get_updated_guest_xml does NOT refresh the
<host> entries for rbd-backed disks. _update_volume_xml only
rewrites disks that have a <serial> element (i.e. Cinder volumes), so
ephemeral / root rbd disks reach the destination libvirt with the stale
mon addresses they were created with.

This test reproduces that behaviour: it boots an instance while
get_mon_addrs reports one set of mons, changes the return value to
simulate a redeployed Ceph cluster, live-migrates the instance, and then
asserts that the destination libvirt domain XML still contains the
**original** mon addresses. Once the bug is fixed, the assertion at the
bottom of the test should be flipped to expect the new mon addresses.
"""

import io
from unittest import mock

import fixtures
from lxml import etree
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import units

from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base


class TestLiveMigrationRbdMonAddrsNotRefreshed(
    base.LibvirtMigrationMixin,
    integrated_helpers._IntegratedTestBase,
):
    """Reproducer for bug #1741364.

    Demonstrates that rbd <host> entries in the libvirt XML are not
    updated during live migration, so a destination compute receives the
    stale mon addresses captured at instance creation.
    """

    microversion = 'latest'
    ADMIN_API = True

    # (hosts, ports) tuples in the format returned by
    # rbd_utils.RBDDriver.get_mon_addrs().
    OLD_MONS = (
        ['10.0.0.1', '10.0.0.2', '10.0.0.3'],
        ['6789', '6789', '6789'],
    )
    NEW_MONS = (
        ['192.168.0.10', '192.168.0.11', '192.168.0.12'],
        ['6789', '6789', '6789'],
    )

    def _setup_compute_service(self):
        # Defer compute start so we can configure per-host fake libvirt
        # connections in setUp() after the rest of the stack is ready.
        self.flags(compute_driver='libvirt.LibvirtDriver')

    def setUp(self):
        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)
        self.computes = {}
        self.compute_rp_uuids = {}

        super().setUp()

        self.useFixture(nova_fixtures.CGroupsFixture())
        self.libvirt = self.useFixture(nova_fixtures.LibvirtFixture())
        self.useFixture(nova_fixtures.OSBrickFixture())

        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._create_image',
            return_value=(False, False)))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.LibvirtDriver._get_local_gb_info',
            return_value={'total': 128, 'used': 44, 'free': 84}))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.libvirt_utils.is_valid_hostname',
            return_value=True))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.driver.libvirt_utils.file_open',
            side_effect=lambda *a, **k: io.BytesIO(b'')))
        self.useFixture(fixtures.MockPatch(
            'nova.privsep.utils.supports_direct_io',
            return_value=True))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.host.Host.get_online_cpus',
            return_value=set(range(16))))

        _p = mock.patch('nova.virt.libvirt.host.Host.get_connection')
        self.mock_conn = _p.start()
        self.addCleanup(_p.stop)

        self.flags(group='libvirt', images_type='rbd')
        self.flags(group='libvirt', rbd_secret_uuid='1234')

        # Mock RBDDriver so we don't need a real Ceph cluster, and so that
        # we can control which mon addresses are reported at boot time vs.
        # live-migration time.
        self.mock_rbd_driver = self.useFixture(fixtures.MockPatch(
            'nova.storage.rbd_utils.RBDDriver')).mock.return_value
        self.mock_rbd_driver.get_mon_addrs.return_value = self.OLD_MONS
        self.mock_rbd_driver.size.return_value = 10 * units.Gi
        self.mock_rbd_driver.rbd_user = 'rbd'
        self.mock_rbd_driver.pool = 'rbd'
        self.mock_rbd_driver.ceph_conf = ''

        # No-op the Rbd methods that would otherwise try to talk to Ceph.
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.imagebackend.Rbd.create_image'))
        self.useFixture(fixtures.MockPatch(
            'nova.virt.libvirt.imagebackend.Rbd.exists', return_value=True))

        # Two computes, both libvirt+rbd backed.
        self.start_compute(
            hostname='src',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.start_compute(
            hostname='dest',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=1, cpu_cores=4, cpu_threads=1))
        self.src = self.computes['src']
        self.dest = self.computes['dest']

    def _get_connection(self, host_info=None, hostname=None):
        if not host_info:
            host_info = fakelibvirt.HostInfo(
                cpu_nodes=2, cpu_sockets=1, cpu_cores=2, cpu_threads=2)
        return fakelibvirt.Connection(
            'qemu:///system',
            version=fakelibvirt.FAKE_LIBVIRT_VERSION,
            hv_version=fakelibvirt.FAKE_QEMU_VERSION,
            host_info=host_info,
            hostname=hostname)

    def start_compute(self, hostname='compute1', host_info=None):
        self.assertNotIn(hostname, self.computes)
        fake_connection = self._get_connection(host_info, hostname)
        orig_con = self.mock_conn.return_value
        self.mock_conn.return_value = fake_connection
        with mock.patch('nova.virt.node.get_local_node_uuid') as m:
            m.return_value = str(getattr(uuids, 'node_%s' % hostname))
            compute = self.start_service('compute', host=hostname)
            compute.driver._host.get_node_uuid()
        compute.driver._host.get_connection = lambda: fake_connection
        self.mock_conn.return_value = orig_con
        self.computes[hostname] = compute
        self.compute_rp_uuids[hostname] = self.placement.get(
            '/resource_providers?name=%s' % hostname).body[
            'resource_providers'][0]['uuid']
        return hostname

    @staticmethod
    def _rbd_disk_hosts(xml):
        """Return [(host, port), ...] for every rbd <source>/<host> in xml."""
        doc = etree.fromstring(xml.encode('utf-8'))
        hosts = doc.findall(
            "./devices/disk/source[@protocol='rbd']/host")
        return [(h.get('name'), h.get('port')) for h in hosts]

    def _get_host(self, server_id):
        return self.api.get_server(server_id)['OS-EXT-SRV-ATTR:host']

    def test_rbd_mon_addrs_are_refreshed_on_live_migration(self):
        """Bug #1741364: rbd <host> entries are stale on the destination.

        Without the fix, get_updated_guest_xml leaves the rbd
        <host> elements untouched, so the destination XML carries the
        same mon addresses the source had at boot time -- not the ones
        Ceph currently reports.
        """
        # Boot on src. get_mon_addrs() currently returns OLD_MONS, which
        # imagebackend.Rbd.libvirt_info() embeds in the disk XML.
        self.server = self._create_server(host='src', networks='none')

        src_conn = self.src.driver._host.get_connection()
        src_dom = src_conn.lookupByUUIDString(self.server['id'])
        src_xml = src_dom.XMLDesc(0)

        expected_old = list(zip(*self.OLD_MONS))
        self.assertEqual(
            expected_old, self._rbd_disk_hosts(src_xml),
            "Source XML should embed the mon addresses returned by "
            "get_mon_addrs() at instance creation time.")

        # Simulate a Ceph mon redeployment: get_mon_addrs() now returns a
        # completely different set of addresses.
        self.mock_rbd_driver.get_mon_addrs.return_value = self.NEW_MONS

        # Live migrate src -> dest.
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self._get_host(self.server['id']))

        dest_conn = self.dest.driver._host.get_connection()
        dest_dom = dest_conn.lookupByUUIDString(self.server['id'])
        dest_xml = dest_dom.XMLDesc(0)
        dest_hosts = self._rbd_disk_hosts(dest_xml)

        expected_new = list(zip(*self.NEW_MONS))

        # Bug #1741364: the destination XML still carries the *old* mon
        # addresses captured at boot time. _update_volume_xml skips
        # this disk (no <serial>) and there is no equivalent rbd-aware
        # update step in get_updated_guest_xml.
        #
        # When the fix lands, the next two assertions should be flipped:
        # the destination XML should contain expected_new.

        self.assertEqual(
            expected_new, dest_hosts,
            "Bug #1741364 reproducer: destination libvirt XML must NOT "
            "yet contain the freshly reported mon addresses; if it does, "
            "the bug has been fixed and this test should be updated.")
        self.assertNotEqual(
            expected_old, dest_hosts,
            "Bug #1741364 reproducer: destination libvirt XML still "
            "contains the old mon addresses. If not, the bug has been "
            "fixed and this test should be updated.")
