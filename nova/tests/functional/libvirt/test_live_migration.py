# Copyright 2021 Red Hat, Inc.
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

import copy
import threading

from lxml import etree
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base as libvirt_base


class LiveMigrationWithLockBase(
    libvirt_base.LibvirtMigrationMixin,
    libvirt_base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    """Base for live migration tests which require live migration to be
    locked for certain period of time and then unlocked afterwards.

    Separate base class is needed because locking mechanism could work
    in an unpredicted way if two tests for the same class would try to
    use it simultaneously. Every test using this mechanism should use
    separate class instance.
    """

    api_major_version = 'v2.1'
    microversion = '2.74'
    ADMIN_API = True

    def setUp(self):
        super().setUp()

        # We will allow only one live migration to be processed at any
        # given period of time
        self.flags(max_concurrent_live_migrations='1')
        self.src_hostname = self.start_compute(hostname='src')
        self.dest_hostname = self.start_compute(hostname='dest')

        self.src = self.computes[self.src_hostname]
        self.dest = self.computes[self.dest_hostname]

        # Live migration's execution could be locked if needed
        self.lock_live_migration = threading.Lock()

    def _migrate_stub(self, domain, destination, params, flags):
        # Execute only if live migration is not locked
        with self.lock_live_migration:
            self.dest.driver._host.get_connection().createXML(
                params['destination_xml'],
                'fake-createXML-doesnt-care-about-flags')
            conn = self.src.driver._host.get_connection()

            # Because migrateToURI3 is spawned in a background thread,
            # this method does not block the upper nova layers. Because
            # we don't want nova to think the live migration has
            # finished until this method is done, the last thing we do
            # is make fakelibvirt's Domain.jobStats() return
            # VIR_DOMAIN_JOB_COMPLETED.
            server = etree.fromstring(
                params['destination_xml']
            ).find('./uuid').text
            dom = conn.lookupByUUIDString(server)
            dom.complete_job()


class LiveMigrationQueuedAbortTestVmStatus(LiveMigrationWithLockBase):
    """Functional test for bug #1949808.

    This test is used to confirm that VM's state is reverted properly
    when queued Live migration is aborted.
    """

    def test_queued_live_migration_abort_vm_status(self):
        # Lock live migrations
        self.lock_live_migration.acquire()

        # Start instances: first one would be used to occupy
        # executor's live migration queue, second one would be used
        # to actually confirm that queued live migrations are
        # aborted properly.
        self.server_a = self._create_server(
            host=self.src_hostname, networks='none')
        self.server_b = self._create_server(
            host=self.src_hostname, networks='none')
        # Issue live migration requests for both servers. We expect that
        # server_a live migration would be running, but locked by
        # self.lock_live_migration and server_b live migration would be
        # queued.
        self._live_migrate(
            self.server_a,
            migration_expected_state='running',
            server_expected_state='MIGRATING'
        )
        self._live_migrate(
            self.server_b,
            migration_expected_state='queued',
            server_expected_state='MIGRATING'
        )

        # Abort live migration for server_b
        serverb_migration = self.api.api_get(
            '/os-migrations?instance_uuid=%s' % self.server_b['id']
        ).body['migrations'].pop()

        self.api.api_delete(
            '/servers/%s/migrations/%s' % (self.server_b['id'],
                                           serverb_migration['id']))
        self._wait_for_migration_status(self.server_b, ['cancelled'])
        # Unlock live migrations and confirm that both servers become
        # active again after successful (server_a) and aborted
        # (server_b) live migrations
        self.lock_live_migration.release()
        self._wait_for_state_change(self.server_a, 'ACTIVE')
        self._wait_for_state_change(self.server_b, 'ACTIVE')


class LiveMigrationQueuedAbortTestLeftoversRemoved(LiveMigrationWithLockBase):
    """Functional test for bug #1960412.

    Placement allocations for live migration and inactive Neutron port
    bindings on destination host created by Nova control plane when live
    migration is initiated should be removed when queued live migration
    is aborted using Nova API.
    """

    def test_queued_live_migration_abort_leftovers_removed(self):
        # Lock live migrations
        self.lock_live_migration.acquire()

        # Start instances: first one would be used to occupy
        # executor's live migration queue, second one would be used
        # to actually confirm that queued live migrations are
        # aborted properly.
        # port_1 is created automatically when neutron fixture is
        # initialized, port_2 is created manually
        self.server_a = self._create_server(
            host=self.src_hostname,
            networks=[{'port': self.neutron.port_1['id']}])
        self.neutron.create_port({'port': self.neutron.port_2})
        self.server_b = self._create_server(
            host=self.src_hostname,
            networks=[{'port': self.neutron.port_2['id']}])
        # Issue live migration requests for both servers. We expect that
        # server_a live migration would be running, but locked by
        # self.lock_live_migration and server_b live migration would be
        # queued.
        self._live_migrate(
            self.server_a,
            migration_expected_state='running',
            server_expected_state='MIGRATING'
        )
        self._live_migrate(
            self.server_b,
            migration_expected_state='queued',
            server_expected_state='MIGRATING'
        )

        # Abort live migration for server_b
        migration_server_a = self.api.api_get(
            '/os-migrations?instance_uuid=%s' % self.server_a['id']
        ).body['migrations'].pop()
        migration_server_b = self.api.api_get(
            '/os-migrations?instance_uuid=%s' % self.server_b['id']
        ).body['migrations'].pop()

        self.api.api_delete(
            '/servers/%s/migrations/%s' % (self.server_b['id'],
                                           migration_server_b['id']))
        self._wait_for_migration_status(self.server_b, ['cancelled'])
        # Unlock live migrations and confirm that both servers become
        # active again after successful (server_a) and aborted
        # (server_b) live migrations
        self.lock_live_migration.release()
        self._wait_for_state_change(self.server_a, 'ACTIVE')
        self._wait_for_migration_status(self.server_a, ['completed'])
        self._wait_for_state_change(self.server_b, 'ACTIVE')

        # Allocations for both successful (server_a) and aborted queued live
        # migration (server_b) should be removed.
        allocations_server_a_migration = self.placement.get(
            '/allocations/%s' % migration_server_a['uuid']
        ).body['allocations']
        self.assertEqual({}, allocations_server_a_migration)
        allocations_server_b_migration = self.placement.get(
            '/allocations/%s' % migration_server_b['uuid']
        ).body['allocations']
        self.assertEqual({}, allocations_server_b_migration)

        # INACTIVE port binding  on destination host should be removed when
        # queued live migration is aborted, so only 1 port binding would
        # exist for ports attached to both servers.
        port_binding_server_a = copy.deepcopy(
            self.neutron._port_bindings[self.neutron.port_1['id']]
        )
        self.assertEqual(1, len(port_binding_server_a))
        self.assertNotIn('src', port_binding_server_a)
        port_binding_server_b = copy.deepcopy(
            self.neutron._port_bindings[self.neutron.port_2['id']]
        )
        self.assertEqual(1, len(port_binding_server_b))
        self.assertNotIn('dest', port_binding_server_b)


class LiveMigrationWithCpuSharedSet(
    libvirt_base.LibvirtMigrationMixin,
    libvirt_base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):

    api_major_version = 'v2.1'
    # Microversion 2.74 is required to boot a server on a specific host,
    # which is used in the below tests.
    microversion = '2.74'
    ADMIN_API = True

    def setUp(self):
        super().setUp()

        self.src_hostname = self.start_compute(hostname='src')
        self.dest_hostname = self.start_compute(hostname='dest')

        self.src = self.computes[self.src_hostname]
        self.dest = self.computes[self.dest_hostname]

    def get_host(self, server_id):
        server = self.api.get_server(server_id)
        return server['OS-EXT-SRV-ATTR:host']

    def test_live_migration_to_different_cpu_shared_set(self):
        """Reproducer for bug 1869804 #1.
        An instance live migrated from a host with a cpu_shared_set to a
        destination host with a different cpu_shared_set should be updated
        to use the destination cpu_shared_set.
        """
        self.flags(cpu_shared_set='0,1', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')
        self.server = self._create_server(host='src', networks='none')

        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        self.assertIn('<vcpu cpuset="0-1">1</vcpu>', xml)

        self.flags(cpu_shared_set='3,4', group='compute')
        self.restart_compute_service('dest')
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        # The destination should be updated to "3-4" but it is not the case.
        self.assertIn('<vcpu cpuset="0-1">1</vcpu>', xml)
        self.assertNotIn('<vcpu cpuset="3-4">1</vcpu>', xml)

    def test_live_migration_to_no_cpu_shared_set(self):
        """Reproducer for bug 1869804 #2.
        An instance live migrated from a host with a cpu_shared_set to a
        destination host without cpu_shared_set should not keep cpuset
        settings.
        """
        self.flags(cpu_shared_set='0,1', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')
        self.server = self._create_server(host='src', networks='none')

        self.reset_flags('cpu_shared_set', group='compute')
        self.restart_compute_service('src')
        self.restart_compute_service('dest')

        # Here we just create a server2 to ensure cpu_shared_set is not
        # configured on destination host.
        self.server2 = self._create_server(host='dest', networks='none')

        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        self.assertIn('<vcpu cpuset="0-1">1</vcpu>', xml)

        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server2['id'])
        xml = dom.XMLDesc(0)
        # This prove that cpu_shared_set is not configured on destination host
        self.assertIn('<vcpu>1</vcpu>', xml)

        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        # The destination cpuset should be removed because the
        # host has no cpu_shared_set configured. Which is not the case due to
        # the bug.
        self.assertIn('<vcpu cpuset="0-1">1</vcpu>', xml)
        self.assertNotIn('<vcpu>1</vcpu>', xml)

    def test_live_migration_from_no_cpu_shared_set_to_cpu_shared_set(self):
        """Reproducer for bug 1869804 #3.
        An instance live migrated from a host without a cpu_shared_set to a
        destination host with cpu_shared_set should be updated to use
        the destination cpu_shared_set.
        """
        self.server = self._create_server(host='src', networks='none')

        conn = self.src.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        self.assertIn('<vcpu>1</vcpu>', xml)

        self.flags(cpu_shared_set='0,1', group='compute')
        self.restart_compute_service('dest')
        self._live_migrate(self.server, 'completed')
        self.assertEqual('dest', self.get_host(self.server['id']))

        conn = self.dest.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server['id'])
        xml = dom.XMLDesc(0)
        # The destination should be updated to "0-1".
        self.assertIn('<vcpu>1</vcpu>', xml)
        self.assertNotIn('<vcpu cpuset="0-1">1</vcpu>', xml)
