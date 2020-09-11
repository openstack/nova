# Copyright (C) 2019 Red Hat, Inc
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

import fixtures

from oslo_config import cfg
from oslo_log import log as logging

from nova.compute import manager as compute_manager
from nova import context
from nova import objects
from nova import test
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base
from nova.tests.unit.virt.libvirt import fake_os_brick_connector
from nova.tests.unit.virt.libvirt import fakelibvirt


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class NUMALiveMigrationBase(base.ServersTestBase,
                            integrated_helpers.InstanceHelperMixin):
    """Base for all the test classes here. Gives us the NUMATopologyFilter and
    small helper methods.
    """
    api_major_version = 'v2.1'
    microversion = 'latest'
    ADDITIONAL_FILTERS = ['NUMATopologyFilter']
    ADMIN_API = True

    def setUp(self):
        super(NUMALiveMigrationBase, self).setUp()

        # NOTE(artom) There's a specific code path that we want to test.
        # There's an instance.save() call in the compute manager's
        # post_live_migration_at_destination(), and another instance.save()
        # call in the libvirt driver's cleanup(), as called from
        # _post_live_migration() in the compute manager. We want to make sure
        # the latter does not clobber any NUMA topology information saved by
        # the former. In order to trigger that code path, two things need to
        # happen. First, the do_cleanup variable needs to be True, in order for
        # driver.cleanup() to actually get called by _post_live_migration().
        # Second, destroy_disks needs to be True as well, in order for
        # cleanup() to enter the code block containing the instance.save()
        # call. Both do_cleanup and destroy_disks are set by
        # _live_migration_cleanup_flags(), so we just monkeypatch it to return
        # what we want regardless of any shared storage configuration.
        self.useFixture(fixtures.MonkeyPatch(
            'nova.compute.manager.ComputeManager.'
            '_live_migration_cleanup_flags',
            lambda *args, **kwargs: (True, True)))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.connector',
            fake_os_brick_connector))

    def _migrate_stub(self, domain, destination, params, flags):
        raise test.TestingException('_migrate_stub() must be implemented in '
                                    ' tests that expect the live migration '
                                    ' to start.')

    def get_host(self, server_id):
        server = self.api.get_server(server_id)
        return server['OS-EXT-SRV-ATTR:host']

    def _get_migration_context(self, instance_uuid):
        ctxt = context.get_admin_context()
        return objects.MigrationContext.get_by_instance_uuid(ctxt,
                                                             instance_uuid)

    def _assert_instance_pinned_cpus(self, uuid, instance_cpus, host_cpus):
        ctxt = context.get_admin_context()
        topology = objects.InstanceNUMATopology.get_by_instance_uuid(
            ctxt, uuid)
        self.assertEqual(1, len(topology.cells))
        # NOTE(artom) DictOfIntegersField has strings as keys, need to convert
        self.assertCountEqual([str(cpu) for cpu in instance_cpus],
                              topology.cells[0].cpu_pinning_raw.keys())
        self.assertCountEqual(host_cpus,
                              topology.cells[0].cpu_pinning_raw.values())

    def _assert_host_consumed_cpus(self, host, cpus):
        ctxt = context.get_admin_context()
        topology = objects.NUMATopology.obj_from_db_obj(
            objects.ComputeNode.get_by_nodename(ctxt, host).numa_topology)
        self.assertCountEqual(cpus, topology.cells[0].pinned_cpus)


class NUMALiveMigrationPositiveBase(NUMALiveMigrationBase):
    """Base for all tests that expect the live migration to actually start.
    Sets up an "environment" with two computes, each with 4 CPUs spead evenly
    across 2 NUMA nodes.
    """

    def setUp(self):
        super(NUMALiveMigrationPositiveBase, self).setUp()
        self.useFixture(fixtures.MonkeyPatch(
            'nova.tests.unit.virt.libvirt.fakelibvirt.Domain.migrateToURI3',
            self._migrate_stub))
        self.migrate_stub_ran = False

    def start_computes_and_servers(self):
        # Start 2 computes
        self.start_compute(
            hostname='host_a',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=4, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))
        self.start_compute(
            hostname='host_b',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=4, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))

        # Create a 2-CPU flavor
        extra_spec = {'hw:cpu_policy': 'dedicated'}
        flavor = self._create_flavor(vcpu=2, extra_spec=extra_spec)

        # Boot 2 servers with 2 CPUs each, one on host_a and one on host_b.
        # Given the cpu_dedicated_set we set earlier, they should both be on
        # CPUs 0,1.
        for server_name, host in [('server_a', 'host_a'),
                                  ('server_b', 'host_b')]:
            server = self._create_server(flavor_id=flavor, host=host,
                                         networks='none')
            setattr(self, server_name,
                    self._wait_for_state_change(server, 'ACTIVE'))
            self.assertEqual(host, self.get_host(server['id']))
            self._assert_instance_pinned_cpus(server['id'], [0, 1], [0, 1])

    def _rpc_pin_host(self, hostname):
        ctxt = context.get_admin_context()
        dest_mgr = self.computes[hostname].manager
        dest_mgr.compute_rpcapi = integrated_helpers.StubComputeRPCAPI(
            '5.2')
        self.assertFalse(
            dest_mgr.compute_rpcapi.router.client(
                ctxt).can_send_version('5.3'))


class NUMALiveMigrationPositiveTests(NUMALiveMigrationPositiveBase):
    """Tests that expect the live migration to succeed. Stubs out fakelibvirt's
    migrateToURI3() with a stub that "suceeds" the migration.
    """

    def _migrate_stub(self, domain, destination, params, flags):
        """This method is designed to stub out libvirt's migrateToURI3 in order
        to test periodics running during the live migration. It also has the
        nice side effect of giving us access to the destination XML so that we
        can assert stuff about it. Because migrateToURI3 is spawned in a
        background thread, this method does not block the upper Nova layers.
        Because we don't want Nova to think the live migration has finished
        until this method is done, the last thing we do is make fakelibvirt's
        Domain.jobStats() return VIR_DOMAIN_JOB_COMPLETED.
        """
        self.assertIsInstance(
            self._get_migration_context(self.server_a['id']),
            objects.MigrationContext)

        # During the migration, server_a is consuming CPUs 0,1 on host_a, while
        # all 4 of host_b's CPU are consumed by server_b and the incoming
        # migration.
        self._assert_host_consumed_cpus('host_a', [0, 1])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])

        host_a_rp = self._get_provider_uuid_by_name('host_a')
        host_b_rp = self._get_provider_uuid_by_name('host_b')
        usages_a = self._get_provider_usages(host_a_rp)
        usages_b = self._get_provider_usages(host_b_rp)
        self.assertEqual(2, usages_a['PCPU'])
        self.assertEqual(4, usages_b['PCPU'])

        # In a real live migration, libvirt and QEMU on the source and
        # destination talk it out, resulting in the instance starting to exist
        # on the destination. Fakelibvirt cannot do that, so we have to
        # manually create the "incoming" instance on the destination
        # fakelibvirt.
        dest = self.computes['host_b']
        dest.driver._host.get_connection().createXML(
            params['destination_xml'],
            'fake-createXML-doesnt-care-about-flags')

        # The resource update periodic task should not change the consumed
        # CPUs, as the migration is still happening. The test should still pass
        # without running periodics, this just makes sure updating available
        # resources does the right thing.
        self._run_periodics()
        self._assert_host_consumed_cpus('host_a', [0, 1])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])

        source = self.computes['host_a']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server_a['id'])
        dom.complete_job()
        self.migrate_stub_ran = True

    def _test(self, pin_dest=False):
        """Live migrate the server on host_a to host_b.
        """
        # Make sure instances initially land on "overlapping" CPUs on both
        # hosts and boot 2 instances.
        self.flags(cpu_dedicated_set='0,1', group='compute')
        self.start_computes_and_servers()

        # Increase cpu_dedicated_set to 0-3, expecting the live migrated server
        # to end up on 2,3.
        self.flags(cpu_dedicated_set='0-3', group='compute')
        self.computes['host_a'] = self.restart_compute_service(
            self.computes['host_a'])
        self.computes['host_b'] = self.restart_compute_service(
            self.computes['host_b'])

        # Live migrate, RPC-pinning the destination host if asked
        if pin_dest:
            self._rpc_pin_host('host_b')
        self._live_migrate(self.server_a, 'completed')
        self.assertEqual('host_b', self.get_host(self.server_a['id']))
        self.assertIsNone(self._get_migration_context(self.server_a['id']))

        # At this point host_a should have no CPUs consumed (server_a has moved
        # to host_b), and host_b should have all of its CPUs consumed. In
        # addition, server_a should be pinned to 2,3 because 0,1 are used up by
        # server_b on host_b. Check this, then run periodics and check again.
        # Running periodics is not necessary for the test to pass, but it's
        # good to know it does the right thing.
        self._assert_host_consumed_cpus('host_a', [])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])
        self._assert_instance_pinned_cpus(self.server_a['id'],
                                          [0, 1], [2, 3])

        self._run_periodics()

        self._assert_host_consumed_cpus('host_a', [])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])
        self._assert_instance_pinned_cpus(self.server_a['id'],
                                          [0, 1], [2, 3])

        self.assertTrue(self.migrate_stub_ran)

        # TODO(artom) It'd be a good idea to live migrate in the other
        # direction here.

    def test_numa_live_migration(self):
        self._test()

    def test_numa_live_migration_dest_pinned(self):
        self._test(pin_dest=True)

    def test_bug_1843639(self):
        """Live migrations in 'accepted' status were not considered in progress
        before the fix for 1845146 merged, and were ignored by the update
        available resources periodic task. From the task's POV, live-migrating
        instances with migration status 'accepted' were considered to be on the
        source, and any resource claims on the destination would get
        erroneously removed. For that to happen, the task had to run at just
        the "right" time, when the migration was in 'accepted' and had not yet
        been moved to 'queued' by live_migration() in the compute manager.

        This test triggers this race by wrapping around live_migration() and
        running the update available resources periodic task while the
        migration is still in 'accepted'.
        """

        self.live_migration_ran = False
        orig_live_migration = compute_manager.ComputeManager.live_migration

        def live_migration(*args, **kwargs):
            self._run_periodics()
            # During the migration, server_a is consuming CPUs 0,1 on host_a,
            # while all 4 of host_b's CPU are consumed by server_b and the
            # incoming # migration.
            self._assert_host_consumed_cpus('host_a', [0, 1])
            self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])

            # The migration should also be in 'accepted' at this point in time.
            ctxt = context.get_admin_context()
            self.assertIsInstance(
                objects.Migration.get_by_instance_and_status(
                    ctxt, self.server_a['id'], 'accepted'),
                objects.Migration)

            self.live_migration_ran = True
            return orig_live_migration(*args, **kwargs)

        self.useFixture(fixtures.MonkeyPatch(
            'nova.compute.manager.ComputeManager.live_migration',
            live_migration))
        self._test()
        self.assertTrue(self.live_migration_ran)


class NUMALiveMigrationRollbackTests(NUMALiveMigrationPositiveBase):
    """Tests that expect the live migration to fail, and exist to test the
    rollback code. Stubs out fakelibvirt's migrateToURI3() with a stub that
    "fails" the migration.
    """

    def _migrate_stub(self, domain, destination, params, flags):
        """Designed to stub fakelibvirt's migrateToURI3 and "fail" the
        live migration by monkeypatching jobStats() to return an error.
        """
        self.assertIsInstance(
            self._get_migration_context(self.server_a['id']),
            objects.MigrationContext)

        # During the migration, server_a is consuming CPUs 0,1 on host_a, while
        # all 4 of host_b's CPU are consumed by server_b and the incoming
        # migration.
        self._assert_host_consumed_cpus('host_a', [0, 1])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])

        # The resource update periodic task should not change the consumed
        # CPUs, as the migration is still happening. As usual, running
        # periodics is not necessary to make the test pass, but it's good to
        # make sure it does the right thing.
        self._run_periodics()
        self._assert_host_consumed_cpus('host_a', [0, 1])
        self._assert_host_consumed_cpus('host_b', [0, 1, 2, 3])

        source = self.computes['host_a']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.server_a['id'])
        dom.fail_job()
        self.migrate_stub_ran = True

    def _test(self, pin_dest=False):
        # Make sure instances initially land on "overlapping" CPUs on both
        # hosts and boot 2 instances.
        self.flags(cpu_dedicated_set='0,1', group='compute')
        self.start_computes_and_servers()

        # Increase cpu_dedicated_set to 0-3, expecting the live migrated server
        # to end up on 2,3.
        self.flags(cpu_dedicated_set='0-3', group='compute')
        self.computes['host_a'] = self.restart_compute_service(
            self.computes['host_a'])
        self.computes['host_b'] = self.restart_compute_service(
            self.computes['host_b'])

        # Live migrate, RPC-pinning the destination host if asked. This is a
        # rollback test, so server_a is expected to remain on host_a.
        if pin_dest:
            self._rpc_pin_host('host_b')
        self._live_migrate(self.server_a, 'failed')
        self.assertEqual('host_a', self.get_host(self.server_a['id']))
        self.assertIsNone(self._get_migration_context(self.server_a['id']))

        # Check consumed and pinned CPUs. Things should be as they were before
        # the live migration, with CPUs 0,1 consumed on both hosts by the 2
        # servers.
        self._assert_host_consumed_cpus('host_a', [0, 1])
        self._assert_host_consumed_cpus('host_b', [0, 1])
        self._assert_instance_pinned_cpus(self.server_a['id'],
                                          [0, 1], [0, 1])

    def test_rollback(self):
        self._test()

    def test_rollback_pinned_dest(self):
        self._test(pin_dest=True)


class NUMALiveMigrationLegacyBase(NUMALiveMigrationPositiveBase):
    """Base for tests that ensure that correct legacy behaviour is observed
    when either the conductor or the source are pinned to an old RPC version.
    Sets up two identical compute hosts and "fills" them with an instance each.
    In such a situation, live migrating one of the instances should fail with
    the new NUMA live migration code, but the old legacy behaviour is for the
    live migration to go through (if forced through the API, thus bypassing the
    scheduler).
    """

    api_major_version = 'v2.1'
    # NOTE(artom) After 2.67 we can no longer bypass the scheduler for live
    # migration, which we need to do here to force the live migration to a host
    # that's already full.
    microversion = '2.67'

    def setUp(self):
        super(NUMALiveMigrationLegacyBase, self).setUp()
        self.flags(compute='auto', group='upgrade_levels')
        self.useFixture(fixtures.MonkeyPatch(
            'nova.objects.service.get_minimum_version_all_cells',
            lambda *args, **kwargs: objects.service.SERVICE_VERSION))

    def _test(self, pin_source, pin_cond, expect_success=True):
        self.start_compute(
            hostname='source',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=2, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))
        self.start_compute(
            hostname='dest',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=2, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))

        ctxt = context.get_admin_context()
        src_mgr = self.computes['source'].manager
        cond_mgr = self.conductor.manager.compute_task_mgr
        if pin_source:
            src_mgr.compute_rpcapi = integrated_helpers.StubComputeRPCAPI(
                '5.2')
        if pin_cond:
            cond_mgr.compute_rpcapi = integrated_helpers.StubComputeRPCAPI(
                '5.2')

        self.assertEqual(
            not pin_source,
            src_mgr.compute_rpcapi.router.client(
                ctxt).can_send_version('5.3'))
        self.assertEqual(
            not pin_cond,
            cond_mgr.compute_rpcapi.router.client(
                ctxt).can_send_version('5.3'))

        extra_spec = {'hw:numa_nodes': 1,
                      'hw:cpu_policy': 'dedicated'}
        flavor = self._create_flavor(vcpu=2, extra_spec=extra_spec)
        server1 = self._create_server(flavor_id=flavor, networks='none')
        server2 = self._create_server(flavor_id=flavor, networks='none')
        if self.get_host(server1['id']) == 'source':
            self.migrating_server = server1
        else:
            self.migrating_server = server2
        self.api.post_server_action(
            self.migrating_server['id'],
            {'os-migrateLive': {'host': 'dest',
                                'block_migration': 'auto',
                                'force': True}})
        self._wait_for_state_change(self.migrating_server, 'ACTIVE')
        if expect_success:
            final_host = 'dest'
            self._wait_for_migration_status(self.migrating_server,
                                            ['completed'])
        else:
            final_host = 'source'
            self._wait_for_migration_status(self.migrating_server, ['failed'])
        self.assertEqual(final_host,
                         self.get_host(self.migrating_server['id']))
        self.assertTrue(self.migrate_stub_ran)


class NUMALiveMigrationLegacyTests(NUMALiveMigrationLegacyBase):
    """Tests that legacy live migration behavior is observed when either the
    source or the conductor are pinned to an old RPC version. Stubs
    fakelibvirt's migrateToURI3 method with a stub that "succeeds" the
    migration.
    """

    def _migrate_stub(self, domain, destination, params, flags):
        # NOTE(artom) This is the crucial bit: by asserting that the migrating
        # instance has no migration context, we're making sure that we're
        # hitting the old, pre-claims code paths.
        self.assertIsNone(
            self._get_migration_context(self.migrating_server['id']))
        dest = self.computes['dest']
        dest.driver._host.get_connection().createXML(
            params['destination_xml'],
            'fake-createXML-doesnt-care-about-flags')

        source = self.computes['source']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.migrating_server['id'])
        dom.complete_job()

        self.migrate_stub_ran = True

    def test_source_pinned_dest_unpinned(self):
        self._test(pin_source=True, pin_cond=False)

    def test_conductor_pinned(self):
        self._test(pin_source=False, pin_cond=True)


class NUMALiveMigrationLegacyRollbackTests(NUMALiveMigrationLegacyBase):
    """Tests that rollback works correctly when either the source or conductor
    are pinned to an old RPC version. Stubs fakelibvirt's migrateToURI3 method
    with a stub that "fails" the migraton in order to trigger rollback.
    """

    def _migrate_stub(self, domain, destination, params, flags):
        # NOTE(artom) This is the crucial bit: by asserting that the migrating
        # instance has no migration context, we're making sure that we're
        # hitting the old, pre-claims code paths.
        self.assertIsNone(
            self._get_migration_context(self.migrating_server['id']))
        source = self.computes['source']
        conn = source.driver._host.get_connection()
        dom = conn.lookupByUUIDString(self.migrating_server['id'])
        dom.fail_job()
        self.migrate_stub_ran = True

    def test_source_pinned_dest_unpinned(self):
        self._test(pin_source=True, pin_cond=False, expect_success=False)

    def test_conductor_pinned(self):
        self._test(pin_source=False, pin_cond=True, expect_success=False)


class NUMALiveMigrationNegativeTests(NUMALiveMigrationBase):
    """Tests that live migrations are refused if the instance cannot fit on the
    destination host (even if the scheduler was bypassed by forcing in the
    API).
    """
    api_major_version = 'v2.1'
    # NOTE(artom) We're trying to test the new NUMA live migration claims, not
    # the scheduler, so we use microversion 2.67, which is the last one where
    # we can still bypass the scheduler and force a live migration to a host.
    microversion = '2.67'

    def test_insufficient_resources(self):
        self.start_compute(
            hostname='host_a',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=3, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))
        self.start_compute(
            hostname='host_b',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=2, cpu_sockets=2, cpu_cores=1, cpu_threads=1,
                kB_mem=10740000))

        extra_spec = {'hw:numa_nodes': 1,
                      'hw:cpu_policy': 'dedicated'}
        flavor = self._create_flavor(vcpu=3, extra_spec=extra_spec)
        server = self._build_server(
            flavor_id=flavor,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6')
        server['networks'] = 'none'
        post = {'server': server}
        server = self.api.post_server(post)
        self._wait_for_state_change(server, 'ACTIVE')
        self.assertEqual('host_a', self.get_host(server['id']))
        # NOTE(artom) Because we use the CastAsCall fixture, we expect the
        # MigrationPreCheckError to be bubbled up to the API as an error 500.
        # TODO(artom) Stop using CastAsCall to make it more realistic.
        self.api.api_post(
            '/servers/%s/action' % server['id'],
            {'os-migrateLive': {'host': 'host_b',
                                'block_migration': 'auto',
                                'force': True}},
            check_response_status=[500])
        self._wait_for_state_change(server, 'ACTIVE')
        self._wait_for_migration_status(server, ['error'])
        self.assertIsNone(self._get_migration_context(server['id']))
        self.assertEqual('host_a', self.get_host(server['id']))
        log_out = self.stdlog.logger.output
        self.assertIn('Migration pre-check error: '
                      'Insufficient compute resources: '
                      'Requested instance NUMA topology cannot fit', log_out)

    def test_different_page_sizes(self):
        self.start_compute(
            hostname='host_a',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=2, cpu_cores=1, cpu_threads=1,
                kB_mem=1024000, mempages={
                    0: fakelibvirt.create_mempages([(4, 256000), (1024, 1000)])
                }))
        self.start_compute(
            hostname='host_b',
            host_info=fakelibvirt.HostInfo(
                cpu_nodes=1, cpu_sockets=2, cpu_cores=1, cpu_threads=1,
                kB_mem=1024000, mempages={
                    0: fakelibvirt.create_mempages([(4, 256000), (2048, 500)]),
                }))

        extra_spec = {'hw:numa_nodes': 1,
                      'hw:cpu_policy': 'dedicated',
                      'hw:mem_page_size': 'large'}
        flavor = self._create_flavor(vcpu=2, memory_mb=512,
                                     extra_spec=extra_spec)
        server = self._build_server(
            flavor_id=flavor,
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6')
        server['networks'] = 'none'
        post = {'server': server}
        server = self.api.post_server(post)
        self._wait_for_state_change(server, 'ACTIVE')
        initial_host = self.get_host(server['id'])
        dest_host = 'host_a' if initial_host == 'host_b' else 'host_b'
        # NOTE(artom) Because we use the CastAsCall fixture, we expect the
        # MigrationPreCheckError to be bubbled up to the API as an error 500.
        # TODO(artom) Stop using CastAsCall to make it more realistic.
        self.api.api_post(
            '/servers/%s/action' % server['id'],
            {'os-migrateLive': {'host': dest_host,
                                'block_migration': 'auto',
                                'force': True}},
            check_response_status=[500])
        self._wait_for_state_change(server, 'ACTIVE')
        self._wait_for_migration_status(server, ['error'])
        self.assertEqual(initial_host, self.get_host(server['id']))
        self.assertIsNone(self._get_migration_context(server['id']))
        log_out = self.stdlog.logger.output
        self.assertIn('Migration pre-check error: '
                      'Insufficient compute resources: '
                      'Requested page size is different from current page '
                      'size.', log_out)
