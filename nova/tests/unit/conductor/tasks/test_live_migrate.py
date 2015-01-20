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

from mox3 import mox

from nova.compute import power_state
from nova.compute import utils as compute_utils
from nova.conductor.tasks import live_migrate
from nova import db
from nova import exception
from nova import objects
from nova.scheduler import utils as scheduler_utils
from nova import test
from nova.tests.unit import fake_instance


class LiveMigrationTaskTestCase(test.NoDBTestCase):
    def setUp(self):
        super(LiveMigrationTaskTestCase, self).setUp()
        self.context = "context"
        self.instance_host = "host"
        self.instance_uuid = "uuid"
        self.instance_image = "image_ref"
        db_instance = fake_instance.fake_db_instance(
                host=self.instance_host,
                uuid=self.instance_uuid,
                power_state=power_state.RUNNING,
                memory_mb=512,
                image_ref=self.instance_image)
        self.instance = objects.Instance._from_db_object(
                self.context, objects.Instance(), db_instance)
        self.destination = "destination"
        self.block_migration = "bm"
        self.disk_over_commit = "doc"
        self._generate_task()

    def _generate_task(self):
        self.task = live_migrate.LiveMigrationTask(self.context,
            self.instance, self.destination, self.block_migration,
            self.disk_over_commit)

    def test_execute_with_destination(self):
        self.mox.StubOutWithMock(self.task, '_check_host_is_up')
        self.mox.StubOutWithMock(self.task, '_check_requested_destination')
        self.mox.StubOutWithMock(self.task.compute_rpcapi, 'live_migration')

        self.task._check_host_is_up(self.instance_host)
        self.task._check_requested_destination()
        self.task.compute_rpcapi.live_migration(self.context,
                host=self.instance_host,
                instance=self.instance,
                dest=self.destination,
                block_migration=self.block_migration,
                migrate_data=None).AndReturn("bob")

        self.mox.ReplayAll()
        self.assertEqual("bob", self.task.execute())

    def test_execute_without_destination(self):
        self.destination = None
        self._generate_task()
        self.assertIsNone(self.task.destination)

        self.mox.StubOutWithMock(self.task, '_check_host_is_up')
        self.mox.StubOutWithMock(self.task, '_find_destination')
        self.mox.StubOutWithMock(self.task.compute_rpcapi, 'live_migration')

        self.task._check_host_is_up(self.instance_host)
        self.task._find_destination().AndReturn("found_host")
        self.task.compute_rpcapi.live_migration(self.context,
                host=self.instance_host,
                instance=self.instance,
                dest="found_host",
                block_migration=self.block_migration,
                migrate_data=None).AndReturn("bob")

        self.mox.ReplayAll()
        self.assertEqual("bob", self.task.execute())

    def test_check_instance_is_running_passes(self):
        self.task._check_instance_is_running()

    def test_check_instance_is_running_fails_when_shutdown(self):
        self.task.instance['power_state'] = power_state.SHUTDOWN
        self.assertRaises(exception.InstanceNotRunning,
                          self.task._check_instance_is_running)

    def test_check_instance_host_is_up(self):
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(self.task.servicegroup_api, 'service_is_up')

        db.service_get_by_compute_host(self.context,
                                       "host").AndReturn("service")
        self.task.servicegroup_api.service_is_up("service").AndReturn(True)

        self.mox.ReplayAll()
        self.task._check_host_is_up("host")

    def test_check_instance_host_is_up_fails_if_not_up(self):
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(self.task.servicegroup_api, 'service_is_up')

        db.service_get_by_compute_host(self.context,
                                       "host").AndReturn("service")
        self.task.servicegroup_api.service_is_up("service").AndReturn(False)

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                self.task._check_host_is_up, "host")

    def test_check_instance_host_is_up_fails_if_not_found(self):
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        db.service_get_by_compute_host(self.context,
                                       "host").AndRaise(exception.NotFound)

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
            self.task._check_host_is_up, "host")

    def test_check_requested_destination(self):
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')
        self.mox.StubOutWithMock(self.task, '_get_compute_info')
        self.mox.StubOutWithMock(self.task.servicegroup_api, 'service_is_up')
        self.mox.StubOutWithMock(self.task.compute_rpcapi,
                                 'check_can_live_migrate_destination')

        db.service_get_by_compute_host(self.context,
                                       self.destination).AndReturn("service")
        self.task.servicegroup_api.service_is_up("service").AndReturn(True)
        hypervisor_details = {
            "hypervisor_type": "a",
            "hypervisor_version": 6.1,
            "free_ram_mb": 513
        }
        self.task._get_compute_info(self.destination)\
                .AndReturn(hypervisor_details)
        self.task._get_compute_info(self.instance_host)\
                .AndReturn(hypervisor_details)
        self.task._get_compute_info(self.destination)\
                .AndReturn(hypervisor_details)

        self.task.compute_rpcapi.check_can_live_migrate_destination(
                self.context, self.instance, self.destination,
                self.block_migration, self.disk_over_commit).AndReturn(
                        "migrate_data")

        self.mox.ReplayAll()
        self.task._check_requested_destination()
        self.assertEqual("migrate_data", self.task.migrate_data)

    def test_check_requested_destination_fails_with_same_dest(self):
        self.task.destination = "same"
        self.task.source = "same"
        self.assertRaises(exception.UnableToMigrateToSelf,
                          self.task._check_requested_destination)

    def test_check_requested_destination_fails_when_destination_is_up(self):
        self.mox.StubOutWithMock(db, 'service_get_by_compute_host')

        db.service_get_by_compute_host(self.context,
            self.destination).AndRaise(exception.NotFound)

        self.mox.ReplayAll()
        self.assertRaises(exception.ComputeServiceUnavailable,
                          self.task._check_requested_destination)

    def test_check_requested_destination_fails_with_not_enough_memory(self):
        self.mox.StubOutWithMock(self.task, '_check_host_is_up')
        self.mox.StubOutWithMock(objects.ComputeNode,
                                 'get_first_node_by_host_for_old_compat')

        self.task._check_host_is_up(self.destination)
        objects.ComputeNode.get_first_node_by_host_for_old_compat(self.context,
            self.destination).AndReturn({"free_ram_mb": 511})

        self.mox.ReplayAll()
        self.assertRaises(exception.MigrationPreCheckError,
                          self.task._check_requested_destination)

    def test_check_requested_destination_fails_with_hypervisor_diff(self):
        self.mox.StubOutWithMock(self.task, '_check_host_is_up')
        self.mox.StubOutWithMock(self.task,
                '_check_destination_has_enough_memory')
        self.mox.StubOutWithMock(self.task, '_get_compute_info')

        self.task._check_host_is_up(self.destination)
        self.task._check_destination_has_enough_memory()
        self.task._get_compute_info(self.instance_host).AndReturn({
            "hypervisor_type": "b"
        })
        self.task._get_compute_info(self.destination).AndReturn({
            "hypervisor_type": "a"
        })

        self.mox.ReplayAll()
        self.assertRaises(exception.InvalidHypervisorType,
                          self.task._check_requested_destination)

    def test_check_requested_destination_fails_with_hypervisor_too_old(self):
        self.mox.StubOutWithMock(self.task, '_check_host_is_up')
        self.mox.StubOutWithMock(self.task,
                '_check_destination_has_enough_memory')
        self.mox.StubOutWithMock(self.task, '_get_compute_info')

        self.task._check_host_is_up(self.destination)
        self.task._check_destination_has_enough_memory()
        self.task._get_compute_info(self.instance_host).AndReturn({
            "hypervisor_type": "a",
            "hypervisor_version": 7
        })
        self.task._get_compute_info(self.destination).AndReturn({
            "hypervisor_type": "a",
            "hypervisor_version": 6
        })

        self.mox.ReplayAll()
        self.assertRaises(exception.DestinationHypervisorTooOld,
                          self.task._check_requested_destination)

    def test_find_destination_works(self):
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        compute_utils.get_image_metadata(self.context,
                self.task.image_api, self.instance_image,
                self.instance).AndReturn("image")
        scheduler_utils.build_request_spec(self.context, mox.IgnoreArg(),
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host1'}])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")

        self.mox.ReplayAll()
        self.assertEqual("host1", self.task._find_destination())

    def test_find_destination_no_image_works(self):
        self.instance['image_ref'] = ''

        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        scheduler_utils.build_request_spec(self.context, None,
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host1'}])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")

        self.mox.ReplayAll()
        self.assertEqual("host1", self.task._find_destination())

    def _test_find_destination_retry_hypervisor_raises(self, error):
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        compute_utils.get_image_metadata(self.context,
                self.task.image_api, self.instance_image,
                self.instance).AndReturn("image")
        scheduler_utils.build_request_spec(self.context, mox.IgnoreArg(),
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host1'}])
        self.task._check_compatible_with_source_hypervisor("host1")\
                .AndRaise(error)

        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host, "host1"]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host2'}])
        self.task._check_compatible_with_source_hypervisor("host2")
        self.task._call_livem_checks_on_host("host2")

        self.mox.ReplayAll()
        self.assertEqual("host2", self.task._find_destination())

    def test_find_destination_retry_with_old_hypervisor(self):
        self._test_find_destination_retry_hypervisor_raises(
                exception.DestinationHypervisorTooOld)

    def test_find_destination_retry_with_invalid_hypervisor_type(self):
        self._test_find_destination_retry_hypervisor_raises(
                exception.InvalidHypervisorType)

    def test_find_destination_retry_with_invalid_livem_checks(self):
        self.flags(migrate_max_retries=1)
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')
        self.mox.StubOutWithMock(self.task, '_call_livem_checks_on_host')

        compute_utils.get_image_metadata(self.context,
                self.task.image_api, self.instance_image,
                self.instance).AndReturn("image")
        scheduler_utils.build_request_spec(self.context, mox.IgnoreArg(),
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host1'}])
        self.task._check_compatible_with_source_hypervisor("host1")
        self.task._call_livem_checks_on_host("host1")\
                .AndRaise(exception.Invalid)

        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host, "host1"]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host2'}])
        self.task._check_compatible_with_source_hypervisor("host2")
        self.task._call_livem_checks_on_host("host2")

        self.mox.ReplayAll()
        self.assertEqual("host2", self.task._find_destination())

    def test_find_destination_retry_exceeds_max(self):
        self.flags(migrate_max_retries=0)
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        self.mox.StubOutWithMock(self.task,
                '_check_compatible_with_source_hypervisor')

        compute_utils.get_image_metadata(self.context,
                self.task.image_api, self.instance_image,
                self.instance).AndReturn("image")
        scheduler_utils.build_request_spec(self.context, mox.IgnoreArg(),
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(
                        [{'host': 'host1'}])
        self.task._check_compatible_with_source_hypervisor("host1")\
                .AndRaise(exception.DestinationHypervisorTooOld)

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost, self.task._find_destination)

    def test_find_destination_when_runs_out_of_hosts(self):
        self.mox.StubOutWithMock(compute_utils, 'get_image_metadata')
        self.mox.StubOutWithMock(scheduler_utils, 'build_request_spec')
        self.mox.StubOutWithMock(scheduler_utils, 'setup_instance_group')
        self.mox.StubOutWithMock(self.task.scheduler_client,
                                 'select_destinations')
        compute_utils.get_image_metadata(self.context,
                self.task.image_api, self.instance_image,
                self.instance).AndReturn("image")
        scheduler_utils.build_request_spec(self.context, mox.IgnoreArg(),
                                           mox.IgnoreArg()).AndReturn({})
        scheduler_utils.setup_instance_group(
            self.context, {}, {'ignore_hosts': [self.instance_host]})
        self.task.scheduler_client.select_destinations(self.context,
                mox.IgnoreArg(), mox.IgnoreArg()).AndRaise(
                        exception.NoValidHost(reason=""))

        self.mox.ReplayAll()
        self.assertRaises(exception.NoValidHost, self.task._find_destination)

    def test_not_implemented_rollback(self):
        self.assertRaises(NotImplementedError, self.task.rollback)
