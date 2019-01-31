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

import time

import mock

from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova.tests import fixtures
from nova.tests.functional.api import client
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier
from nova.virt import fake

COMPUTE_VERSION_OLD_ATTACH_FLOW = \
    compute_api.CINDER_V3_ATTACH_MIN_COMPUTE_VERSION - 1


class TestInstanceNotificationSampleWithMultipleCompute(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(compute_driver='fake.FakeLiveMigrateDriver')
        self.flags(use_neutron=True)
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSampleWithMultipleCompute, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixtureNewAttachFlow(self)
        self.useFixture(self.cinder)
        self.useFixture(fixtures.AllServicesCurrent())

    def test_multiple_compute_actions(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._wait_for_notification('instance.create.end')
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        # server will boot on the 'compute' host
        fake.set_nodes(['host2'])
        self.addCleanup(fake.restore_nodes)
        self.compute2 = self.start_service('compute', host='host2')

        actions = [
            self._test_live_migration_rollback,
            self._test_live_migration_abort,
            self._test_live_migration_success,
            self._test_evacuate_server,
            self._test_live_migration_force_complete
        ]

        for action in actions:
            fake_notifier.reset()
            action(server)
            # Ensure that instance is in active state after an action
            self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_live_migration_cleanup_flags', return_value=[True, False])
    @mock.patch('nova.compute.rpcapi.ComputeAPI.pre_live_migration',
                side_effect=exception.DestinationDiskExists(path='path'))
    def _test_live_migration_rollback(self, server, mock_migration,
                                      mock_flags):
        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
                'force': True,
            }
        }
        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_notification(
            'instance.live_migration_rollback_dest.end')

        # 0. instance.live_migration_rollback.start
        # 1. instance.live_migration_rollback.end
        # 2. instance.live_migration_rollback_dest.start
        # 3. instance.live_migration_rollback_dest.end
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-live_migration_rollback-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-live_migration_rollback-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self._verify_notification(
            'instance-live_migration_rollback_dest-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-live_migration_rollback_dest-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def _test_live_migration_success(self, server):
        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
                'force': True,
            }
        }
        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.live_migration_pre.end')
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-live_migration_pre-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-live_migration_pre-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        migrations = self.admin_api.get_active_migrations(server['id'])
        self.assertEqual(1, len(migrations))

        self._wait_for_notification('instance.live_migration_post.end')
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-live_migration_post-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-live_migration_post_dest-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])
        self._verify_notification(
            'instance-live_migration_post_dest-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-live_migration_post-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    def _test_live_migration_abort(self, server):
        post = {
            "os-migrateLive": {
                "host": "host2",
                "block_migration": False,
                "force": True
            }
        }

        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'MIGRATING')

        migrations = self._wait_and_get_migrations(server)

        self.admin_api.delete_migration(server['id'], migrations[0]['id'])
        self._wait_for_notification('instance.live_migration_abort.start')
        self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        # NOTE(gibi): the intance.live_migration_rollback notification emitted
        # after the instance.live_migration_abort notification so we have to
        # wait for the rollback to ensure we can assert both notifications
        # below
        self._wait_for_notification('instance.live_migration_rollback.end')
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-live_migration_pre-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-live_migration_pre-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self._verify_notification(
            'instance-live_migration_abort-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-live_migration_abort-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])
        self._verify_notification(
            'instance-live_migration_rollback-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-live_migration_rollback-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    def _test_evacuate_server(self, server):
        services = self.admin_api.get_services(host='host2',
                                               binary='nova-compute')
        service_id = services[0]['id']
        self.admin_api.put_service(service_id, {'forced_down': True})
        evacuate = {
            'evacuate': {
                'host': 'compute',
                'force': True
            }
        }

        self.admin_api.post_server_action(server['id'], evacuate)
        self._wait_for_state_change(self.api, server,
                                    expected_status='REBUILD')
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        notifications = self._get_notifications('instance.evacuate')
        self.assertEqual(1, len(notifications))
        self._verify_notification(
            'instance-evacuate',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=notifications[0])
        self.admin_api.put_service(service_id, {'forced_down': False})

    def _test_live_migration_force_complete(self, server):
        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
                'force': True,
            }
        }
        self.admin_api.post_server_action(server['id'], post)

        self._wait_for_state_change(self.api, server, 'MIGRATING')

        migrations = self._wait_and_get_migrations(server)
        migration_id = migrations[0]['id']
        self.admin_api.force_complete_migration(server['id'], migration_id)

        self._wait_for_notification(
            'instance.live_migration_force_complete.end')

        # 0. instance.live_migration_pre.start
        # 1. instance.live_migration_pre.end
        # 2. instance.live_migration_force_complete.start
        # 3. instance.live_migration_force_complete.end
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-live_migration_force_complete-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-live_migration_force_complete-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])


class TestInstanceNotificationSampleWithMultipleComputeOldAttachFlow(
        TestInstanceNotificationSampleWithMultipleCompute):

    def setUp(self):
        self.flags(compute_driver='fake.FakeLiveMigrateDriver')
        self.flags(use_neutron=True)
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSampleWithMultipleCompute, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixture(self)
        self.useFixture(self.cinder)

        patcher = self.mock_min_service_version = \
            mock.patch('nova.objects.Service.get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
        self.mock_min_service_version = patcher.start()
        self.addCleanup(patcher.stop)


class TestInstanceNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(use_neutron=True)
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSample, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixtureNewAttachFlow(self)
        self.useFixture(self.cinder)

    def _wait_until_swap_volume(self, server, volume_id):
        for i in range(50):
            volume_attachments = self.api.get_server_volumes(server['id'])
            if len(volume_attachments) > 0:
                for volume_attachment in volume_attachments:
                    if volume_attachment['volumeId'] == volume_id:
                        return
            time.sleep(0.5)
        self.fail('Volume swap operation failed.')

    def test_instance_action(self):
        # A single test case is used to test most of the instance action
        # notifications to avoid booting up an instance for every action
        # separately.
        # Every instance action test function shall make sure that after the
        # function the instance is in active state and usable by other actions.
        # Therefore some action especially delete cannot be used here as
        # recovering from that action would mean to recreate the instance and
        # that would go against the whole purpose of this optimization

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})

        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        actions = [
            self._test_power_off_on_server,
            self._test_restore_server,
            self._test_suspend_resume_server,
            self._test_pause_unpause_server,
            self._test_shelve_and_shelve_offload_server,
            self._test_unshelve_server,
            self._test_resize_and_revert_server,
            self._test_snapshot_server,
            self._test_reboot_server,
            self._test_reboot_server_error,
            self._test_trigger_crash_dump,
            self._test_volume_detach_attach_server,
            self._test_rescue_unrescue_server,
            self._test_soft_delete_server,
            self._test_attach_volume_error,
            self._test_interface_attach_and_detach,
            self._test_interface_attach_error,
            self._test_lock_unlock_instance,
        ]

        for action in actions:
            fake_notifier.reset()
            action(server)
            # Ensure that instance is in active state after an action
            self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

    def test_create_delete_server(self):
        fake_trusted_certs = ['cert-id-1', 'cert-id-2']
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}],
                          'tags': ['tag'],
                          'trusted_image_certificates': fake_trusted_certs})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        # NOTE(gibi): The wait_unit_deleted() call polls the REST API to see if
        # the instance is disappeared however the _delete_instance() in
        # compute/manager destroys the instance first then send the
        # instance.delete.end notification. So to avoid race condition the test
        # needs to wait for the notification as well here.
        self._wait_for_notification('instance.delete.end')
        self.assertEqual(9, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                         fake_notifier.VERSIONED_NOTIFICATIONS)

        # This list needs to be in order.
        expected_notifications = [
            'instance-create-start',
            'instance-create-end',
            'instance-update-tags-action',
            'instance-volume_attach-start',
            'instance-volume_attach-end',
            'instance-delete-start',
            'instance-shutdown-start',
            'instance-shutdown-end',
            'instance-delete-end'
        ]
        for idx, notification in enumerate(expected_notifications):
            self._verify_notification(
                notification,
                replacements={
                    'reservation_id': server['reservation_id'],
                    'uuid': server['id']},
                actual=fake_notifier.VERSIONED_NOTIFICATIONS[idx])

    @mock.patch('nova.compute.manager.ComputeManager._build_resources')
    def test_create_server_error(self, mock_build):
        def _build_resources(*args, **kwargs):
            raise exception.FlavorDiskTooSmall()

        mock_build.side_effect = _build_resources

        fake_trusted_certs = ['cert-id-1', 'cert-id-2']
        server = self._boot_a_server(
            expected_status='ERROR',
            extra_params={'networks': [{'port': self.neutron.port_1['id']}],
                          'tags': ['tag'],
                          'trusted_image_certificates': fake_trusted_certs})

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn('raise exception.FlavorDiskTooSmall()', tb)

        self._verify_notification(
            'instance-create-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-create-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def test_instance_exists_usage_audit(self):
        # TODO(xavvior): Should create a functional test for the
        # "instance_usage_audit" periodic task. We didn't find usable
        # solution for this problem, however we tried to test it in
        # several ways.
        pass

    def test_instance_exists(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})

        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        # Let's generate some bandwidth usage data.
        # Just call the periodic task directly for simplicity
        self.compute.manager._poll_bandwidth_usage(context.get_admin_context())

        fake_notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server,
                                    expected_status='REBUILD')
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        notifications = self._get_notifications('instance.exists')
        self._verify_notification(
            'instance-exists',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']
            },
            actual=notifications[0])

    def _verify_instance_update_steps(self, steps, notifications,
                                      initial=None):
        replacements = {}
        if initial:
            replacements = initial
        for i, step in enumerate(steps):
            replacements.update(step)
            self._verify_notification(
                'instance-update',
                replacements=replacements,
                actual=notifications[i])
        return replacements

    def test_create_delete_server_with_instance_update(self):
        # This makes server network creation synchronous which is necessary
        # for notification samples that expect instance.info_cache.network_info
        # to be set.
        self.useFixture(fixtures.SpawnIsSynchronousFixture())
        self.flags(notify_on_state_change='vm_and_task_state',
                   group='notifications')

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        instance_updates = self._wait_for_notifications('instance.update', 8)

        # The first notification comes from the nova-conductor, the
        # eighth notification comes from nova-api the
        # rest is from the nova-compute. To keep the test simpler
        # assert this fact and then modify the publisher_id of the
        # first and eighth notification to match the template
        self.assertEqual('nova-conductor:fake-mini',
                         instance_updates[0]['publisher_id'])
        self.assertEqual('nova-api:fake-mini',
                         instance_updates[7]['publisher_id'])
        instance_updates[0]['publisher_id'] = 'nova-compute:fake-mini'
        instance_updates[7]['publisher_id'] = 'nova-compute:fake-mini'

        create_steps = [
            # nothing -> scheduling
            {'reservation_id': server['reservation_id'],
             'uuid': server['id'],
             'host': None,
             'node': None,
             'state_update.new_task_state': 'scheduling',
             'state_update.old_task_state': 'scheduling',
             'state_update.state': 'building',
             'state_update.old_state': 'building',
             'state': 'building'},

            # scheduling -> building
            {
             'state_update.new_task_state': None,
             'state_update.old_task_state': 'scheduling',
             'task_state': None},

            # scheduled
            {'host': 'compute',
             'node': 'fake-mini',
             'state_update.old_task_state': None,
             'updated_at': '2012-10-29T13:42:11Z'},

            # building -> networking
            {'state_update.new_task_state': 'networking',
             'state_update.old_task_state': 'networking',
             'task_state': 'networking'},

            # networking -> block_device_mapping
            {'state_update.new_task_state': 'block_device_mapping',
             'state_update.old_task_state': 'networking',
             'task_state': 'block_device_mapping',
             'ip_addresses': [{
                 "nova_object.name": "IpPayload",
                 "nova_object.namespace": "nova",
                 "nova_object.version": "1.0",
                 "nova_object.data": {
                     "mac": "fa:16:3e:4c:2c:30",
                     "address": "192.168.1.3",
                     "port_uuid": "ce531f90-199f-48c0-816c-13e38010b442",
                     "meta": {},
                     "version": 4,
                     "label": "private-network",
                     "device_name": "tapce531f90-19"
                 }}]
            },

            # block_device_mapping -> spawning
            {'state_update.new_task_state': 'spawning',
             'state_update.old_task_state': 'block_device_mapping',
             'task_state': 'spawning',
             },

            # spawning -> active
            {'state_update.new_task_state': None,
             'state_update.old_task_state': 'spawning',
             'state_update.state': 'active',
             'launched_at': '2012-10-29T13:42:11Z',
             'state': 'active',
             'task_state': None,
             'power_state': 'running'},

            # tag added
            {'state_update.old_task_state': None,
             'state_update.old_state': 'active',
             'tags': ['tag1']},
        ]

        replacements = self._verify_instance_update_steps(
                create_steps, instance_updates)

        fake_notifier.reset()

        # Let's generate some bandwidth usage data.
        # Just call the periodic task directly for simplicity
        self.compute.manager._poll_bandwidth_usage(context.get_admin_context())

        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)

        instance_updates = self._get_notifications('instance.update')
        self.assertEqual(2, len(instance_updates))

        delete_steps = [
            # active -> deleting
            {'state_update.new_task_state': 'deleting',
             'state_update.old_task_state': 'deleting',
             'state_update.old_state': 'active',
             'state': 'active',
             'task_state': 'deleting',
             'bandwidth': [
                 {'nova_object.namespace': 'nova',
                  'nova_object.name': 'BandwidthPayload',
                  'nova_object.data':
                      {'network_name': 'private-network',
                       'out_bytes': 0,
                       'in_bytes': 0},
                  'nova_object.version': '1.0'}],
             'tags': ["tag1"],
             'block_devices': [{
                "nova_object.data": {
                    "boot_index": None,
                    "delete_on_termination": False,
                    "device_name": "/dev/sdb",
                    "tag": None,
                    "volume_id": "a07f71dc-8151-4e7d-a0cc-cd24a3f11113"
                },
                "nova_object.name": "BlockDevicePayload",
                "nova_object.namespace": "nova",
                "nova_object.version": "1.0"
              }]
            },

            # deleting -> deleted
            {'state_update.new_task_state': None,
             'state_update.old_task_state': 'deleting',
             'state_update.old_state': 'active',
             'state_update.state': 'deleted',
             'state': 'deleted',
             'task_state': None,
             'terminated_at': '2012-10-29T13:42:11Z',
             'ip_addresses': [],
             'power_state': 'pending',
             'bandwidth': [],
             'tags': ["tag1"],
             'block_devices': [{
                "nova_object.data": {
                    "boot_index": None,
                    "delete_on_termination": False,
                    "device_name": "/dev/sdb",
                    "tag": None,
                    "volume_id": "a07f71dc-8151-4e7d-a0cc-cd24a3f11113"
                },
                "nova_object.name": "BlockDevicePayload",
                "nova_object.namespace": "nova",
                "nova_object.version": "1.0"
              }]
            },
        ]

        self._verify_instance_update_steps(delete_steps, instance_updates,
                                           initial=replacements)

    def _test_power_off_on_server(self, server):
        self.api.post_server_action(server['id'], {'os-stop': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHUTOFF')
        self.api.post_server_action(server['id'], {'os-start': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-power_off-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-power_off-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        self._verify_notification(
            'instance-power_on-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-power_on-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def _test_shelve_and_shelve_offload_server(self, server):
        self.flags(shelved_offload_time=-1)
        self.api.post_server_action(server['id'], {'shelve': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHELVED')

        self.assertEqual(3, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-shelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self._verify_notification(
            'instance-shelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])

        fake_notifier.reset()
        self.api.post_server_action(server['id'], {'shelveOffload': {}})
        # we need to wait for the instance.host to become None as well before
        # we can unshelve to make sure that the unshelve.start notification
        # payload is stable as the compute manager first sets the instance
        # state then a bit later sets the instance.host to None.
        self._wait_for_server_parameter(self.api, server,
                                        {'status': 'SHELVED_OFFLOADED',
                                         'OS-EXT-SRV-ATTR:host': None})

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-shelve_offload-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-shelve_offload-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

    def _test_unshelve_server(self, server):
        # setting the shelved_offload_time to 0 should set the
        # instance status to 'SHELVED_OFFLOADED'
        self.flags(shelved_offload_time = 0)
        self.api.post_server_action(server['id'], {'shelve': {}})
        # we need to wait for the instance.host to become None as well before
        # we can unshelve to make sure that the unshelve.start notification
        # payload is stable as the compute manager first sets the instance
        # state then a bit later sets the instance.host to None.
        self._wait_for_server_parameter(self.api, server,
                                        {'status': 'SHELVED_OFFLOADED',
                                         'OS-EXT-SRV-ATTR:host': None})

        post = {'unshelve': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        self.assertEqual(7, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-unshelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])
        self._verify_notification(
            'instance-unshelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[6])

    def _test_suspend_resume_server(self, server):
        post = {'suspend': {}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'SUSPENDED')

        post = {'resume': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        # Four versioned notification are generated.
        # 0. instance-suspend-start
        # 1. instance-suspend-end
        # 2. instance-resume-start
        # 3. instance-resume-end
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-suspend-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-suspend-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        self._verify_notification(
            'instance-resume-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-resume-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

        self.flags(reclaim_instance_interval=0)

    def _test_pause_unpause_server(self, server):
        self.api.post_server_action(server['id'], {'pause': {}})
        self._wait_for_state_change(self.api, server, 'PAUSED')

        self.api.post_server_action(server['id'], {'unpause': {}})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Four versioned notifications are generated
        # 0. instance-pause-start
        # 1. instance-pause-end
        # 2. instance-unpause-start
        # 3. instance-unpause-end
        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-pause-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-pause-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self._verify_notification(
            'instance-unpause-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-unpause-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

    def _test_resize_and_revert_server(self, server):
        self.flags(allow_resize_to_same_host=True)
        other_flavor_body = {
            'flavor': {
                'name': 'other_flavor',
                'ram': 256,
                'vcpus': 1,
                'disk': 1,
                'id': 'd5a8bb54-365a-45ae-abdb-38d249df7845'
            }
        }
        other_flavor_id = self.api.post_flavor(other_flavor_body)['id']
        extra_specs = {
            "extra_specs": {
                "hw:watchdog_action": "reset"}}
        self.admin_api.post_extra_spec(other_flavor_id, extra_specs)

        # Ignore the create flavor notification
        fake_notifier.reset()

        post = {
            'resize': {
                'flavorRef': other_flavor_id
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')

        self.assertEqual(7, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        # ignore instance.exists
        fake_notifier.VERSIONED_NOTIFICATIONS.pop(0)
        # This list needs to be in order.
        expected_notifications = [
            'instance-resize_prep-start',
            'instance-resize_prep-end',
            'instance-resize-start',
            'instance-resize-end',
            'instance-resize_finish-start',
            'instance-resize_finish-end'
        ]
        for idx, notification in enumerate(expected_notifications):
            self._verify_notification(
                notification,
                replacements={
                    'reservation_id': server['reservation_id'],
                    'uuid': server['id']},
                actual=fake_notifier.VERSIONED_NOTIFICATIONS[idx])

        fake_notifier.reset()
        # the following is the revert server request
        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        self.assertEqual(3, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        # ignore instance.exists
        fake_notifier.VERSIONED_NOTIFICATIONS.pop(0)
        self._verify_notification(
            'instance-resize_revert-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-resize_revert-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    @mock.patch('nova.compute.manager.ComputeManager._reschedule',
                return_value=True)
    @mock.patch('nova.compute.manager.ComputeManager._prep_resize')
    def test_resize_server_error_but_reschedule_was_success(
            self, mock_prep_resize, mock_reschedule):
        """Test it, when the prep_resize method raise an exception,
        but the reschedule_resize_or_reraise was successful and
        scheduled the resize. In this case we get a notification
        about the exception, which caused the prep_resize error.
        """
        def _build_resources(*args, **kwargs):
            raise exception.FlavorDiskTooSmall()
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self.flags(allow_resize_to_same_host=True)
        other_flavor_body = {
            'flavor': {
                'name': 'other_flavor_error',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'id': 'a22d5517-147c-4147-a0d1-e698df5cd4e9'
            }
        }
        other_flavor_id = self.api.post_flavor(other_flavor_body)['id']

        post = {
            'resize': {
                'flavorRef': other_flavor_id
            }
        }
        fake_notifier.reset()
        mock_prep_resize.side_effect = _build_resources
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.resize.error')
        # 0: instance-exists
        # 1: instance-resize_prep-start
        # 2: instance-resize-error
        # 3: instance-resize_prep-end
        self.assertLessEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                             'Unexpected number of notifications: %s' %
                             fake_notifier.VERSIONED_NOTIFICATIONS)
        # Note(gibi): There is also an instance.exists notification emitted
        # during the rescheduling

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[2]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.FlavorDiskTooSmall()", tb)

        self._verify_notification('instance-resize-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])

    @mock.patch('nova.compute.manager.ComputeManager._reschedule')
    @mock.patch('nova.compute.manager.ComputeManager._prep_resize')
    def test_resize_server_error_and_reschedule_was_failed(
            self, mock_prep_resize, mock_reschedule):
        """Test it, when the prep_resize method raise an exception,
        after trying again with the reschedule_resize_or_reraise method
        call, but the rescheduled also was unsuccessful. In this
        case called the exception block.
        In the exception block send a notification about error.
        At end called the six.reraise(*exc_info), which not
        send another error.
        """
        def _build_resources(*args, **kwargs):
            raise exception.FlavorDiskTooSmall()

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self.flags(allow_resize_to_same_host=True)
        other_flavor_body = {
            'flavor': {
                'name': 'other_flavor_error',
                'ram': 512,
                'vcpus': 1,
                'disk': 1,
                'id': 'a22d5517-147c-4147-a0d1-e698df5cd4e9'
            }
        }
        other_flavor_id = self.api.post_flavor(other_flavor_body)['id']

        post = {
            'resize': {
                'flavorRef': other_flavor_id
            }
        }
        fake_notifier.reset()
        mock_prep_resize.side_effect = _build_resources
        # This isn't realistic that _reschedule would raise FlavorDiskTooSmall,
        # but it's needed for the notification sample to work.
        mock_reschedule.side_effect = _build_resources
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, expected_status='ERROR')
        self._wait_for_notification('compute.exception')
        # There should be the following notifications.
        # 0: instance-exists
        # 1: instance-resize_prep-start
        # 2: instance-resize-error
        # 3: instance-resize_prep-end
        # 4: compute.exception
        #    (via the wrap_exception decorator on
        #    the ComputeManager.prep_resize method.)
        self.assertEqual(5, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                         'Unexpected number of notifications: %s' %
                         fake_notifier.VERSIONED_NOTIFICATIONS)

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[2]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.FlavorDiskTooSmall()", tb)

        self._verify_notification('instance-resize-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY
            },
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])

    def _test_snapshot_server(self, server):
        post = {'createImage': {'name': 'test-snap'}}
        response = self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.snapshot.end')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-snapshot-start',
            replacements={
                'snapshot_image_id': response['image_id'],
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
                    actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-snapshot-end',
            replacements={
                'snapshot_image_id': response['image_id'],
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def test_rebuild_server(self):
        # NOTE(gabor_antal): Rebuild changes the image used by the instance,
        # therefore the actions tested in test_instance_action had to be in
        # specific order. To avoid this problem, rebuild was moved from
        # test_instance_action to its own method.

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        fake_notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {},
            }
        }
        self.api.post_server_action(server['id'], post)
        # Before going back to ACTIVE state
        # server state need to be changed to REBUILD state
        self._wait_for_state_change(self.api, server,
                                    expected_status='REBUILD')
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        # 0. instance.rebuild_scheduled
        # 1. instance.exists
        # 2. instance.rebuild.start
        # 3. instance.detach.start
        # 4. instance.detach.end
        # 5. instance.rebuild.end
        # The compute/manager will detach every volume during rebuild
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-rebuild_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-rebuild-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-rebuild-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    def test_rebuild_server_with_trusted_cert(self):
        # NOTE(gabor_antal): Rebuild changes the image used by the instance,
        # therefore the actions tested in test_instance_action had to be in
        # specific order. To avoid this problem, rebuild was moved from
        # test_instance_action to its own method.

        create_trusted_certs = ['cert-id-1', 'cert-id-2']
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}],
                          'trusted_image_certificates': create_trusted_certs})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        fake_notifier.reset()

        rebuild_trusted_certs = ['rebuild-cert-id-1', 'rebuild-cert-id-2']
        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {},
                'trusted_image_certificates': rebuild_trusted_certs,
            }
        }
        self.api.post_server_action(server['id'], post)
        # Before going back to ACTIVE state
        # server state need to be changed to REBUILD state
        self._wait_for_state_change(self.api, server,
                                    expected_status='REBUILD')
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        # 0. instance.rebuild_scheduled
        # 1. instance.exists
        # 2. instance.rebuild.start
        # 3. instance.detach.start
        # 4. instance.detach.end
        # 5. instance.rebuild.end
        # The compute/manager will detach every volume during rebuild
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-rebuild_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-rebuild-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-rebuild-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_do_rebuild_instance_with_claim')
    def test_rebuild_server_exc(self, mock_rebuild):
        def _virtual_interface_create_failed(*args, **kwargs):
            # A real error that could come out of driver.spawn() during rebuild
            raise exception.VirtualInterfaceCreateException()

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        fake_notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        mock_rebuild.side_effect = _virtual_interface_create_failed
        self._wait_for_state_change(self.api, server, expected_status='ERROR')
        notification = self._get_notifications('instance.rebuild.error')
        self.assertEqual(1, len(notification))

        tb = notification[0]['payload']['nova_object.data']['fault'][
                'nova_object.data']['traceback']
        self.assertIn('raise exception.VirtualInterfaceCreateException()', tb)

        self._verify_notification(
            'instance-rebuild-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None,
                'fault.traceback': self.ANY},
            actual=notification[0])

    def _test_restore_server(self, server):
        self.flags(reclaim_instance_interval=30)
        self.api.delete_server(server['id'])
        self._wait_for_state_change(self.api, server, 'SOFT_DELETED')
        # we don't want to test soft_delete here
        fake_notifier.reset()
        self.api.post_server_action(server['id'], {'restore': {}})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-restore-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-restore-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_reboot_server(self, server):
        post = {'reboot': {'type': 'HARD'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.reboot.start')
        self._wait_for_notification('instance.reboot.end')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-reboot-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-reboot-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    @mock.patch('nova.virt.fake.SmallFakeDriver.reboot')
    def _test_reboot_server_error(self, server, mock_reboot):
        def _hard_reboot(*args, **kwargs):
            raise exception.UnsupportedVirtType(virt="FakeVirt")
        mock_reboot.side_effect = _hard_reboot
        post = {'reboot': {'type': 'HARD'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.reboot.start')
        self._wait_for_notification('instance.reboot.error')
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.UnsupportedVirtType", tb)

        self._verify_notification(
            'instance-reboot-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-reboot-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _detach_volume_from_server(self, server, volume_id):
        self.api.delete_server_volume(server['id'], volume_id)
        self._wait_for_notification('instance.volume_detach.end')

    def _volume_swap_server(self, server, attachement_id, volume_id):
        self.api.put_server_volume(server['id'], attachement_id, volume_id)

    def test_volume_swap_server(self):
        server = self._boot_a_server(
            extra_params={'networks':
                          [{'port': self.neutron.port_1['id']}]})

        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        self.cinder.swap_volume_instance_uuid = server['id']

        self._volume_swap_server(server, self.cinder.SWAP_OLD_VOL,
                                 self.cinder.SWAP_NEW_VOL)
        self._wait_until_swap_volume(server, self.cinder.SWAP_NEW_VOL)
        # NOTE(gibi): the new volume id can appear on the API earlier than the
        # volume_swap.end notification emitted. So to make the test stable
        # we have to wait for the volume_swap.end notification directly.
        self._wait_for_notification('instance.volume_swap.end')

        self.assertEqual(7, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                         'Unexpected number of versioned notifications. '
                         'Got: %s' % fake_notifier.VERSIONED_NOTIFICATIONS)
        self._verify_notification(
            'instance-volume_swap-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])
        self._verify_notification(
            'instance-volume_swap-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[6])

    def _do_setup_server_and_error_flag(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_ERR_OLD_VOL)

        self.cinder.attachment_error_id = self.cinder.SWAP_ERR_ATTACH_ID

        return server

    def test_volume_swap_server_with_error(self):
        server = self._do_setup_server_and_error_flag()

        self._volume_swap_server(server, self.cinder.SWAP_ERR_OLD_VOL,
                                 self.cinder.SWAP_ERR_NEW_VOL)
        self._wait_for_notification('compute.exception')

        # Eight versioned notifications are generated.
        # 0. instance-create-start
        # 1. instance-create-end
        # 2. instance-update
        # 3. instance-volume_attach-start
        # 4. instance-volume_attach-end
        # 5. instance-volume_swap-start
        # 6. instance-volume_swap-error
        # 7. compute.exception
        self.assertLessEqual(7, len(fake_notifier.VERSIONED_NOTIFICATIONS),
                             'Unexpected number of versioned notifications. '
                             'Got: %s' % fake_notifier.VERSIONED_NOTIFICATIONS)
        block_devices = [{
            "nova_object.data": {
                "boot_index": None,
                "delete_on_termination": False,
                "device_name": "/dev/sdb",
                "tag": None,
                "volume_id": self.cinder.SWAP_ERR_OLD_VOL
            },
            "nova_object.name": "BlockDevicePayload",
            "nova_object.namespace": "nova",
            "nova_object.version": "1.0"
        }]
        self._verify_notification(
            'instance-volume_swap-start',
            replacements={
                'new_volume_id': self.cinder.SWAP_ERR_NEW_VOL,
                'old_volume_id': self.cinder.SWAP_ERR_OLD_VOL,
                'block_devices': block_devices,
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

        tb1 = fake_notifier.VERSIONED_NOTIFICATIONS[6]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("_swap_volume", tb1)
        tb2 = fake_notifier.VERSIONED_NOTIFICATIONS[7]['payload'][
            'nova_object.data']['traceback']
        self.assertIn("_swap_volume", tb2)

        self._verify_notification(
            'instance-volume_swap-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'block_devices': block_devices,
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[6])

    def test_resize_confirm_server(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        self.admin_api.post_extra_spec(
            '2', {"extra_specs": {"hw:watchdog_action": "disabled"}})
        self.flags(allow_resize_to_same_host=True)
        post = {'resize': {'flavorRef': '2'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'VERIFY_RESIZE')
        fake_notifier.reset()

        post = {'confirmResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-resize_confirm-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-resize_confirm-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_trigger_crash_dump(self, server):
        post = {'trigger_crash_dump': None}
        self.api.post_server_action(server['id'], post)

        self._wait_for_notification('instance.trigger_crash_dump.end')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-trigger_crash_dump-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-trigger_crash_dump-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_volume_detach_attach_server(self, server):
        self._detach_volume_from_server(server, self.cinder.SWAP_OLD_VOL)

        # 0. volume_detach-start
        # 1. volume_detach-end
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        fake_notifier.reset()
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        # 0. volume_attach-start
        # 1. volume_attach-end
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-volume_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-volume_attach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_rescue_unrescue_server(self, server):
        # Both "rescue" and "unrescue" notification asserts are made here
        # rescue notification asserts
        post = {
            "rescue": {
                "rescue_image_ref": 'a2459075-d96c-40d5-893e-577ff92e721c'
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'RESCUE')

        # 0. instance.rescue.start
        # 1. instance.exists
        # 2. instance.rescue.end
        self.assertEqual(3, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-rescue-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-rescue-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        fake_notifier.reset()

        # unrescue notification asserts
        post = {
            'unrescue': None
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-unrescue-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-unrescue-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_soft_delete_server(self, server):
        self.flags(reclaim_instance_interval=30)
        self.api.delete_server(server['id'])
        self._wait_for_state_change(self.api, server, 'SOFT_DELETED')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-soft_delete-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-soft_delete-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
        self.flags(reclaim_instance_interval=0)
        # Leave instance in normal, active state
        self.api.post_server_action(server['id'], {'restore': {}})

    def _do_test_attach_volume_error(self, server, mock_attach):
        def attach_volume(*args, **kwargs):
            raise exception.CinderConnectionFailed(
                reason="Connection timed out")
        mock_attach.side_effect = attach_volume

        post = {"volumeAttachment": {"volumeId": self.cinder.SWAP_NEW_VOL}}
        self.api.post_server_volume(server['id'], post)

        self._wait_for_notification('instance.volume_attach.error')

        block_devices = [
            # Add by default at boot
            {'nova_object.data': {'boot_index': None,
                                  'delete_on_termination': False,
                                  'tag': None,
                                  'device_name': '/dev/sdb',
                                  'volume_id': self.cinder.SWAP_OLD_VOL},
             'nova_object.name': 'BlockDevicePayload',
             'nova_object.namespace': 'nova',
             'nova_object.version': '1.0'},
            # Attaching it right now
            {'nova_object.data': {'boot_index': None,
                                  'delete_on_termination': False,
                                  'tag': None,
                                  'device_name': '/dev/sdc',
                                  'volume_id': self.cinder.SWAP_NEW_VOL},
             'nova_object.name': 'BlockDevicePayload',
             'nova_object.namespace': 'nova',
             'nova_object.version': '1.0'}]

        # 0. volume_attach-start
        # 1. volume_attach-error
        # 2. compute.exception
        # We only rely on the first 2 notifications, in this case we don't
        # care about the exception notification.
        self.assertLessEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-volume_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'block_devices': block_devices,
                'volume_id': self.cinder.SWAP_NEW_VOL,
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("CinderConnectionFailed:", tb)

        self._verify_notification(
            'instance-volume_attach-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'block_devices': block_devices,
                'volume_id': self.cinder.SWAP_NEW_VOL,
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    @mock.patch('nova.volume.cinder.API.attachment_update')
    def _test_attach_volume_error(self, server, mock_attach):
        self._do_test_attach_volume_error(server, mock_attach)

    def _test_interface_attach_and_detach(self, server):
        post = {
            'interfaceAttachment': {
                'net_id': fixtures.NeutronFixture.network_1['id']
            }
        }
        self.api.attach_interface(server['id'], post)
        self._wait_for_notification('instance.interface_attach.end')
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-interface_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-interface_attach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        fake_notifier.reset()
        self.assertEqual(0, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        self.api.detach_interface(
            server['id'],
            fixtures.NeutronFixture.port_2['id'])
        self._wait_for_notification('instance.interface_detach.end')
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-interface_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-interface_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    @mock.patch('nova.virt.fake.SmallFakeDriver.attach_interface')
    def _test_interface_attach_error(self, server, mock_driver):
        def _unsuccessful_attach_interface(*args, **kwargs):
            raise exception.InterfaceAttachFailed("dummy")
        mock_driver.side_effect = _unsuccessful_attach_interface
        post = {
            'interfaceAttachment': {
                'net_id': fixtures.NeutronFixture.network_1['id']
            }
        }
        self.assertRaises(
            client.OpenStackApiException,
            self.api.attach_interface, server['id'], post)
        self._wait_for_notification('instance.interface_attach.error')
        # 0. instance.interface_attach.start
        # 1. instance.interface_attach.error
        # 2. compute.exception
        self.assertLessEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-interface_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])

        tb = fake_notifier.VERSIONED_NOTIFICATIONS[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.InterfaceAttachFailed", tb)

        self._verify_notification(
            'instance-interface_attach-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_lock_unlock_instance(self, server):
        self.api.post_server_action(server['id'], {'lock': {}})
        self._wait_for_server_parameter(self.api, server, {'locked': True})
        self.api.post_server_action(server['id'], {'unlock': {}})
        self._wait_for_server_parameter(self.api, server, {'locked': False})
        # Two versioned notifications are generated
        # 0. instance-lock
        # 1. instance-unlock

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-lock',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-unlock',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])


class TestInstanceNotificationSampleOldAttachFlow(
        TestInstanceNotificationSample):

    def setUp(self):
        self.flags(use_neutron=True)
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSample, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixture(self)
        self.useFixture(self.cinder)

        patcher = self.mock_min_service_version = \
            mock.patch('nova.objects.Service.get_minimum_version',
                       return_value=COMPUTE_VERSION_OLD_ATTACH_FLOW)
        self.mock_min_service_version = patcher.start()
        self.addCleanup(patcher.stop)

    def _do_setup_server_and_error_flag(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_ERR_OLD_VOL)

        self.cinder.swap_volume_instance_error_uuid = server['id']

        return server

    @mock.patch('nova.volume.cinder.API.attach')
    def _test_attach_volume_error(self, server, mock_attach):
        self._do_test_attach_volume_error(server, mock_attach)

    def test_rebuild_server_with_trusted_cert(self):
        # Skipping this test as trusted cert support needs a later service
        # version than this test class is limited to.
        pass
