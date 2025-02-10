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
from unittest import mock


from nova import exception
from nova.tests import fixtures
from nova.tests.functional.api import client
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.volume import cinder


class TestInstanceNotificationSampleWithMultipleCompute(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(compute_driver='fake.FakeLiveMigrateDriver')
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSampleWithMultipleCompute, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixture(self)
        self.useFixture(self.cinder)
        self.useFixture(fixtures.AllServicesCurrent())

    def test_multiple_compute_actions(self):
        # There are not going to be real network-vif-plugged events coming
        # so don't wait for them.
        self.flags(live_migration_wait_for_vif_plug=False, group='compute')
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._wait_for_notification('instance.create.end')
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        # server will boot on the 'compute' host
        self.compute2 = self.start_service('compute', host='host2')

        actions = [
            (self._test_live_migration_rollback, 'ACTIVE'),
            (self._test_live_migration_abort, 'ACTIVE'),
            (self._test_live_migration_success, 'ACTIVE'),
            (self._test_evacuate_server, 'SHUTOFF'),
            (self._test_live_migration_force_complete, 'ACTIVE'),
        ]

        for action, expected_state in actions:
            self.notifier.reset()
            action(server)
            # Ensure that instance is in active state after an action
            self._wait_for_state_change(server, expected_state)

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
            }
        }
        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_notification(
            'instance.live_migration_rollback_dest.end')

        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance.live_migration_rollback.start
        # 3. instance.live_migration_rollback.end
        # 4. instance.live_migration_rollback_dest.start
        # 5. instance.live_migration_rollback_dest.end
        self.assertEqual(6, len(self.notifier.versioned_notifications),
                         [x['event_type'] for x in
                          self.notifier.versioned_notifications])
        self._verify_notification(
            'instance-live_migration_rollback-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-live_migration_rollback-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])
        self._verify_notification(
            'instance-live_migration_rollback_dest-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-live_migration_rollback_dest-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])

    def _test_live_migration_success(self, server):
        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
            }
        }
        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.live_migration_pre.end')
        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance.live_migration_pre.start
        # 3. instance.live_migration_pre.end
        self.assertEqual(4, len(self.notifier.versioned_notifications),
                         [x['event_type'] for x in
                          self.notifier.versioned_notifications])
        self._verify_notification(
            'instance-live_migration_pre-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-live_migration_pre-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])
        migrations = self.admin_api.get_active_migrations(server['id'])
        self.assertEqual(1, len(migrations))

        self._wait_for_notification('instance.live_migration_post.end')
        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance.live_migration_pre.start
        # 3. instance.live_migration_pre.end
        # 4. instance.live_migration_post.start
        # 5. instance.live_migration_post_dest.start
        # 6. instance.live_migration_post_dest.end
        # 7. instance.live_migration_post.end
        self.assertEqual(8, len(self.notifier.versioned_notifications),
                         [x['event_type'] for x in
                          self.notifier.versioned_notifications])
        self._verify_notification(
            'instance-live_migration_post-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-live_migration_post_dest-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])
        self._verify_notification(
            'instance-live_migration_post_dest-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[6])
        self._verify_notification(
            'instance-live_migration_post-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[7])

    def _test_live_migration_abort(self, server):
        post = {
            "os-migrateLive": {
                "host": "host2",
                "block_migration": False,
            }
        }

        self.admin_api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'MIGRATING')

        migrations = self._wait_and_get_migrations(server)

        self.admin_api.delete_migration(server['id'], migrations[0]['id'])
        self._wait_for_notification('instance.live_migration_abort.start')
        self._wait_for_state_change(server, 'ACTIVE')
        # NOTE(gibi): the instance.live_migration_rollback notification emitted
        # after the instance.live_migration_abort notification so we have to
        # wait for the rollback to ensure we can assert both notifications
        # below
        self._wait_for_notification('instance.live_migration_rollback.end')

        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance.live_migration_pre.start
        # 3. instance.live_migration_pre.end
        # 4. instance.live_migration_abort.start
        # 5. instance.live_migration_abort.end
        # 6. instance.live_migration_rollback.start
        # 7. instance.live_migration_rollback.end
        self.assertEqual(8, len(self.notifier.versioned_notifications),
                         [x['event_type'] for x in
                          self.notifier.versioned_notifications])
        self._verify_notification(
            'instance-live_migration_pre-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-live_migration_pre-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])
        self._verify_notification(
            'instance-live_migration_abort-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-live_migration_abort-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])
        self._verify_notification(
            'instance-live_migration_rollback-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[6])
        self._verify_notification(
            'instance-live_migration_rollback-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[7])

    def _test_evacuate_server(self, server):
        services = self.admin_api.get_services(host='host2',
                                               binary='nova-compute')
        service_id = services[0]['id']
        self.compute2.stop()
        self.admin_api.put_service(service_id, {'forced_down': True})

        post_args = {
            "host": "compute"
        }

        self._evacuate_server(
            server, extra_post_args=post_args, expected_host='compute')

        notifications = self._get_notifications('instance.evacuate')
        self.assertEqual(1, len(notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-evacuate',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=notifications[0])
        self.compute2.start()
        self._wait_for_migration_status(server, ['completed'])
        self.admin_api.put_service(service_id, {'forced_down': False})

    def _test_live_migration_force_complete(self, server):
        # In the scenario evacuate happened before which stopped the
        # server.
        self._start_server(server)
        self._wait_for_state_change(server, 'ACTIVE')
        self.notifier.reset()

        post = {
            'os-migrateLive': {
                'host': 'host2',
                'block_migration': True,
            }
        }
        self.admin_api.post_server_action(server['id'], post)

        self._wait_for_state_change(server, 'MIGRATING')

        migrations = self._wait_and_get_migrations(server)
        migration_id = migrations[0]['id']
        self.admin_api.force_complete_migration(server['id'], migration_id)

        # Note that we wait for instance.live_migration_force_complete.end but
        # by the time we check versioned notifications received we could have
        # entered ComputeManager._post_live_migration which could emit up to
        # four other notifications:
        # - instance.live_migration_post.start
        # - instance.live_migration_post_dest.start
        # - instance.live_migration_post_dest.end
        # - instance.live_migration_post.end
        # We are not concerned about those in this test so that's why we stop
        # once we get instance.live_migration_force_complete.end and assert
        # we got at least 6 notifications.
        self._wait_for_notification(
            'instance.live_migration_force_complete.end')

        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance.live_migration_pre.start
        # 3. instance.live_migration_pre.end
        # 4. instance.live_migration_force_complete.start
        # 5. instance.live_migration_force_complete.end
        self.assertGreaterEqual(len(self.notifier.versioned_notifications), 6,
                                self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-live_migration_force_complete-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-live_migration_force_complete-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])


class TestInstanceNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(bdms_in_notifications='True', group='notifications')
        super(TestInstanceNotificationSample, self).setUp()
        self.neutron = fixtures.NeutronFixture(self)
        self.useFixture(self.neutron)
        self.cinder = fixtures.CinderFixture(self)
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
            self._test_lock_unlock_instance_with_reason,
        ]

        for action in actions:
            self.notifier.reset()
            action(server)
            # Ensure that instance is in active state after an action
            self._wait_for_state_change(server, 'ACTIVE')

            # if the test step did not raised then we consider the step as
            # succeeded. We drop the logs to avoid causing subunit parser
            # errors due to logging too much at the end of the test case.
            self.stdlog.delete_stored_logs()

    def test_create_delete_server(self):
        fake_trusted_certs = ['cert-id-1', 'cert-id-2']
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}],
                          'tags': ['tag'],
                          'trusted_image_certificates': fake_trusted_certs})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        self._delete_server(server)
        # NOTE(gibi): The wait_unit_deleted() call polls the REST API to see if
        # the instance is disappeared however the _delete_instance() in
        # compute/manager destroys the instance first then send the
        # instance.delete.end notification. So to avoid race condition the test
        # needs to wait for the notification as well here.
        self._wait_for_notification('instance.delete.end')
        self.assertEqual(9, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)

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
                actual=self.notifier.versioned_notifications[idx])

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

        # 0. scheduler.select_destinations.start
        # 1. scheduler.select_destinations.end
        # 2. instance-create-start
        # 3. instance-create-error
        self.assertEqual(4, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)

        tb = self.notifier.versioned_notifications[3]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn('raise exception.FlavorDiskTooSmall()', tb)

        self._verify_notification(
            'instance-create-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-create-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=self.notifier.versioned_notifications[3])

        self.notifier.reset()

        self._delete_server(server)

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-delete-start_not_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-delete-end_not_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

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

        self.notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, expected_status='REBUILD')
        self._wait_for_state_change(server, expected_status='ACTIVE')

        notifications = self._get_notifications('instance.exists')
        self._verify_notification(
            'instance-exists',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']
            },
            actual=notifications[0])

    def test_delete_server_while_compute_is_down(self):

        server = self._boot_a_server(
            expected_status='ACTIVE',
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        service_id = self.api.get_service_id('nova-compute')
        self.admin_api.put_service_force_down(service_id, True)
        self.notifier.reset()

        self._delete_server(server)

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-delete-start_compute_down',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-delete-end_compute_down',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self.admin_api.put_service_force_down(service_id, False)

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
                     "label": "private",
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

        self.notifier.reset()

        self._delete_server(server)

        instance_updates = self._get_notifications('instance.update')
        self.assertEqual(2, len(instance_updates),
                         self.notifier.versioned_notifications)

        delete_steps = [
            # active -> deleting
            {'state_update.new_task_state': 'deleting',
             'state_update.old_task_state': 'deleting',
             'state_update.old_state': 'active',
             'state': 'active',
             'task_state': 'deleting',
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
        self._wait_for_state_change(server, expected_status='SHUTOFF')
        self.api.post_server_action(server['id'], {'os-start': {}})
        self._wait_for_state_change(server, expected_status='ACTIVE')

        self.assertEqual(4, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-power_off-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-power_off-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self._verify_notification(
            'instance-power_on-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-power_on-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])

    def _test_shelve_and_shelve_offload_server(self, server):
        self.flags(shelved_offload_time=-1)
        self.api.post_server_action(server['id'], {'shelve': {}})
        self._wait_for_state_change(server, expected_status='SHELVED')

        self.assertEqual(3, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-shelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])
        self._verify_notification(
            'instance-shelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])

        self.notifier.reset()
        self.api.post_server_action(server['id'], {'shelveOffload': {}})
        # we need to wait for the instance.host to become None as well before
        # we can unshelve to make sure that the unshelve.start notification
        # payload is stable as the compute manager first sets the instance
        # state then a bit later sets the instance.host to None.
        self._wait_for_server_parameter(server,
                                        {'status': 'SHELVED_OFFLOADED',
                                         'OS-EXT-SRV-ATTR:host': None})

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-shelve_offload-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-shelve_offload-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self.api.post_server_action(server['id'], {'unshelve': None})
        self._wait_for_state_change(server, 'ACTIVE')
        self._wait_for_notification('instance.unshelve.end')

    def _test_unshelve_server(self, server):
        # setting the shelved_offload_time to 0 should set the
        # instance status to 'SHELVED_OFFLOADED'
        self.flags(shelved_offload_time = 0)
        self.api.post_server_action(server['id'], {'shelve': {}})
        # we need to wait for the instance.host to become None as well before
        # we can unshelve to make sure that the unshelve.start notification
        # payload is stable as the compute manager first sets the instance
        # state then a bit later sets the instance.host to None.
        self._wait_for_server_parameter(server,
                                        {'status': 'SHELVED_OFFLOADED',
                                         'OS-EXT-SRV-ATTR:host': None})

        post = {'unshelve': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'ACTIVE')
        self._wait_for_notification('instance.unshelve.end')
        self.assertEqual(9, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-unshelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[7])
        self._verify_notification(
            'instance-unshelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[8])

    def _test_suspend_resume_server(self, server):
        post = {'suspend': {}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'SUSPENDED')

        post = {'resume': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'ACTIVE')

        # Four versioned notification are generated.
        # 0. instance-suspend-start
        # 1. instance-suspend-end
        # 2. instance-resume-start
        # 3. instance-resume-end
        self.assertEqual(4, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-suspend-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-suspend-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self._verify_notification(
            'instance-resume-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-resume-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])

        self.flags(reclaim_instance_interval=0)

    def _test_pause_unpause_server(self, server):
        self.api.post_server_action(server['id'], {'pause': {}})
        self._wait_for_state_change(server, 'PAUSED')

        self.api.post_server_action(server['id'], {'unpause': {}})
        self._wait_for_state_change(server, 'ACTIVE')

        # Four versioned notifications are generated
        # 0. instance-pause-start
        # 1. instance-pause-end
        # 2. instance-unpause-start
        # 3. instance-unpause-end
        self.assertEqual(4, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-pause-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-pause-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])
        self._verify_notification(
            'instance-unpause-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-unpause-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])

    def _build_destination_payload(self):
        cell1 = self.cell_mappings.get('cell1')
        return {
            'nova_object.version': '1.0',
            'nova_object.namespace': 'nova',
            'nova_object.name': 'DestinationPayload',
            'nova_object.data': {
                'aggregates': None,
                'cell': {
                    'nova_object.version': '2.0',
                    'nova_object.namespace': 'nova',
                    'nova_object.name': 'CellMappingPayload',
                    'nova_object.data': {
                        'disabled': False,
                        'name': u'cell1',
                        'uuid': cell1.uuid
                    }
                }
            }
        }

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
        self.notifier.reset()

        post = {
            'resize': {
                'flavorRef': other_flavor_id
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')

        self._pop_and_verify_dest_select_notification(server['id'],
            replacements={
                'ignore_hosts': [],
                'flavor.memory_mb': other_flavor_body['flavor']['ram'],
                'flavor.name': other_flavor_body['flavor']['name'],
                'flavor.flavorid': other_flavor_id,
                'flavor.extra_specs': extra_specs['extra_specs'],
                'requested_destination': self._build_destination_payload()})

        self.assertEqual(7, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        # ignore instance.exists
        self.notifier.versioned_notifications.pop(0)

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
                actual=self.notifier.versioned_notifications[idx])

        self.notifier.reset()
        # the following is the revert server request
        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'ACTIVE')

        self.assertEqual(3, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        # ignore instance.exists
        self.notifier.versioned_notifications.pop(0)
        self._verify_notification(
            'instance-resize_revert-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-resize_revert-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    @mock.patch('nova.compute.manager.ComputeManager._prep_resize')
    def test_resize_server_error_but_reschedule_was_success(
            self, mock_prep_resize):
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
        self.notifier.reset()
        mock_prep_resize.side_effect = _build_resources
        # NOTE(gibi): the first resize_instance call (from the API) should be
        # unaffected so that we can reach _prep_resize at all. But the
        # subsequent resize_instance call (from _reschedule_resize_or_reraise)
        # needs to be mocked as there is no alternative host to resize to.
        patcher = mock.patch.object(self.compute.manager.compute_task_api,
                                    'resize_instance')
        self.addCleanup(patcher.stop)
        patcher.start()
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.resize.error')
        self._pop_and_verify_dest_select_notification(server['id'],
            replacements={
                'ignore_hosts': [],
                'flavor.name': other_flavor_body['flavor']['name'],
                'flavor.flavorid': other_flavor_id,
                'flavor.extra_specs': {},
                'requested_destination': self._build_destination_payload()})
        # 0: instance-exists
        # 1: instance-resize_prep-start
        # 2: instance-resize-error
        # 3: instance-resize_prep-end
        self.assertLessEqual(2, len(self.notifier.versioned_notifications),
                             'Unexpected number of notifications: %s' %
                             self.notifier.versioned_notifications)
        # Note(gibi): There is also an instance.exists notification emitted
        # during the rescheduling

        tb = self.notifier.versioned_notifications[2]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.FlavorDiskTooSmall()", tb)

        self._verify_notification('instance-resize-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY
            },
            actual=self.notifier.versioned_notifications[2])

    @mock.patch('nova.compute.manager.ComputeManager._prep_resize')
    def test_resize_server_error_and_reschedule_was_failed(
            self, mock_prep_resize):
        """Test it, when the prep_resize method raise an exception,
        after trying again with the reschedule_resize_or_reraise method
        call, but the rescheduled also was unsuccessful. In this
        case called the exception block.
        In the exception block send a notification about error.
        At end called raising an exception based on *exc_info,
        which not send another error.
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
        self.notifier.reset()
        mock_prep_resize.side_effect = _build_resources
        # NOTE(gibi): the first resize_instance call (from the API) should be
        # unaffected so that we can reach _prep_resize at all. But the
        # subsequent resize_instance call (from _reschedule_resize_or_reraise)
        # needs to fail. It isn't realistic that resize_instance would raise
        # FlavorDiskTooSmall, but it's needed for the notification sample
        # to work.
        patcher = mock.patch.object(self.compute.manager.compute_task_api,
                                    'resize_instance',
                                    side_effect=_build_resources)
        self.addCleanup(patcher.stop)
        patcher.start()
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, expected_status='ERROR')
        self._wait_for_notification('compute.exception')
        # There should be the following notifications after scheduler's
        # select_destination notifications:
        # 0: instance-exists
        # 1: instance-resize_prep-start
        # 2: instance-resize-error
        # 3: instance-resize_prep-end
        # 4: compute.exception
        #    (via the wrap_exception decorator on
        #    the ComputeManager.prep_resize method.)
        self._pop_and_verify_dest_select_notification(server['id'],
            replacements={
                'ignore_hosts': [],
                'flavor.name': other_flavor_body['flavor']['name'],
                'flavor.flavorid': other_flavor_id,
                'flavor.extra_specs': {},
                'requested_destination': self._build_destination_payload()})
        self.assertEqual(5, len(self.notifier.versioned_notifications),
                         'Unexpected number of notifications: %s' %
                         self.notifier.versioned_notifications)

        tb = self.notifier.versioned_notifications[2]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.FlavorDiskTooSmall()", tb)

        self._verify_notification('instance-resize-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY
            },
            actual=self.notifier.versioned_notifications[2])

    def _test_snapshot_server(self, server):
        post = {'createImage': {'name': 'test-snap'}}
        response = self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.snapshot.end')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-snapshot-start',
            replacements={
                'snapshot_image_id': response['image_id'],
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
                    actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-snapshot-end',
            replacements={
                'snapshot_image_id': response['image_id'],
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def test_rebuild_server(self):
        # NOTE(gabor_antal): Rebuild changes the image used by the instance,
        # therefore the actions tested in test_instance_action had to be in
        # specific order. To avoid this problem, rebuild was moved from
        # test_instance_action to its own method.

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        self.notifier.reset()

        image_ref = 'a2459075-d96c-40d5-893e-577ff92e721c'
        post = {
            'rebuild': {
                'imageRef': image_ref,
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        # Before going back to ACTIVE state
        # server state need to be changed to REBUILD state
        self._wait_for_state_change(server, expected_status='REBUILD')
        self._wait_for_state_change(server, expected_status='ACTIVE')

        self._pop_and_verify_dest_select_notification(server['id'],
            replacements={
                'image.container_format': 'ami',
                'image.disk_format': 'ami',
                'image.id': image_ref,
                'image.properties': {
                    'nova_object.data': {},
                    'nova_object.name': 'ImageMetaPropsPayload',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.13',
                },
                'image.size': 58145823,
                'image.tags': [],
                'scheduler_hints': {'_nova_check_type': ['rebuild']},
                'force_hosts': 'compute',
                'force_nodes': 'fake-mini',
                'requested_destination': self._build_destination_payload()})

        # 0. instance.rebuild_scheduled
        # 1. instance.exists
        # 2. instance.rebuild.start
        # 3. instance.detach.start
        # 4. instance.detach.end
        # 5. instance.rebuild.end
        # The compute/manager will detach every volume during rebuild
        self.assertEqual(6, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-rebuild_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-rebuild-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-rebuild-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'trusted_image_certificates': None},
            actual=self.notifier.versioned_notifications[5])

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

        self.notifier.reset()

        image_ref = 'a2459075-d96c-40d5-893e-577ff92e721c'
        rebuild_trusted_certs = ['rebuild-cert-id-1', 'rebuild-cert-id-2']
        post = {
            'rebuild': {
                'imageRef': image_ref,
                'metadata': {},
                'trusted_image_certificates': rebuild_trusted_certs,
            }
        }
        self.api.post_server_action(server['id'], post)
        # Before going back to ACTIVE state
        # server state need to be changed to REBUILD state
        self._wait_for_state_change(server, expected_status='REBUILD')
        self._wait_for_state_change(server, expected_status='ACTIVE')

        self._pop_and_verify_dest_select_notification(server['id'],
            replacements={
                'image.container_format': 'ami',
                'image.disk_format': 'ami',
                'image.id': image_ref,
                'image.properties': {
                    'nova_object.data': {},
                    'nova_object.name': 'ImageMetaPropsPayload',
                    'nova_object.namespace': 'nova',
                    'nova_object.version': '1.13',
                },
                'image.size': 58145823,
                'image.tags': [],
                'scheduler_hints': {'_nova_check_type': ['rebuild']},
                'force_hosts': 'compute',
                'force_nodes': 'fake-mini',
                'requested_destination': self._build_destination_payload()})

        # 0. instance.rebuild_scheduled
        # 1. instance.exists
        # 2. instance.rebuild.start
        # 3. instance.detach.start
        # 4. instance.detach.end
        # 5. instance.rebuild.end
        # The compute/manager will detach every volume during rebuild
        self.assertEqual(6, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-rebuild_scheduled',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-rebuild-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[3])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'task_state': 'rebuilding',
                'architecture': None,
                'image_uuid': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[4])
        self._verify_notification(
            'instance-rebuild-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_do_rebuild_instance_with_claim')
    def test_rebuild_server_exc(self, mock_rebuild):
        def _virtual_interface_create_failed(*args, **kwargs):
            # A real error that could come out of driver.spawn() during rebuild
            raise exception.VirtualInterfaceCreateException()

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        self.notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        mock_rebuild.side_effect = _virtual_interface_create_failed
        self._wait_for_state_change(server, expected_status='ERROR')
        notification = self._get_notifications('instance.rebuild.error')
        self.assertEqual(1, len(notification),
                         self.notifier.versioned_notifications)

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
        self._wait_for_state_change(server, 'SOFT_DELETED')
        # we don't want to test soft_delete here
        self.notifier.reset()
        self.api.post_server_action(server['id'], {'restore': {}})
        self._wait_for_state_change(server, 'ACTIVE')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-restore-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-restore-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_reboot_server(self, server):
        post = {'reboot': {'type': 'HARD'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.reboot.start')
        self._wait_for_notification('instance.reboot.end')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-reboot-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-reboot-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    @mock.patch('nova.virt.fake.SmallFakeDriver.reboot')
    def _test_reboot_server_error(self, server, mock_reboot):
        def _hard_reboot(*args, **kwargs):
            raise exception.UnsupportedVirtType(virt="FakeVirt")
        mock_reboot.side_effect = _hard_reboot
        post = {'reboot': {'type': 'HARD'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.reboot.start')
        self._wait_for_notification('instance.reboot.error')
        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)

        tb = self.notifier.versioned_notifications[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.UnsupportedVirtType", tb)

        self._verify_notification(
            'instance-reboot-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-reboot-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=self.notifier.versioned_notifications[1])

    def _detach_volume_from_server(self, server, volume_id):
        self.api.delete_server_volume(server['id'], volume_id)
        self._wait_for_notification('instance.volume_detach.end')

    def _volume_swap_server(self, server, attachment_id, volume_id):
        self.api.put_server_volume(server['id'], attachment_id, volume_id)

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

        self.assertEqual(7, len(self.notifier.versioned_notifications),
                         'Unexpected number of versioned notifications. '
                         'Got: %s' % self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-volume_swap-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[5])
        self._verify_notification(
            'instance-volume_swap-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[6])

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
        self.assertLessEqual(7, len(self.notifier.versioned_notifications),
                             'Unexpected number of versioned notifications. '
                             'Got: %s' % self.notifier.versioned_notifications)
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
            actual=self.notifier.versioned_notifications[5])

        tb1 = self.notifier.versioned_notifications[6]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("_swap_volume", tb1)
        tb2 = self.notifier.versioned_notifications[7]['payload'][
            'nova_object.data']['traceback']
        self.assertIn("_swap_volume", tb2)

        self._verify_notification(
            'instance-volume_swap-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'block_devices': block_devices,
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=self.notifier.versioned_notifications[6])

    def test_resize_confirm_server(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)
        self.admin_api.post_extra_spec(
            '2', {"extra_specs": {"hw:watchdog_action": "disabled"}})
        self.flags(allow_resize_to_same_host=True)
        post = {'resize': {'flavorRef': '2'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'VERIFY_RESIZE')
        self.notifier.reset()

        post = {'confirmResize': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'ACTIVE')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-resize_confirm-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-resize_confirm-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_trigger_crash_dump(self, server):
        post = {'trigger_crash_dump': None}
        self.api.post_server_action(server['id'], post)

        self._wait_for_notification('instance.trigger_crash_dump.end')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-trigger_crash_dump-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-trigger_crash_dump-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_volume_detach_attach_server(self, server):
        self._detach_volume_from_server(server, self.cinder.SWAP_OLD_VOL)

        # 0. volume_detach-start
        # 1. volume_detach-end
        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-volume_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-volume_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self.notifier.reset()
        self._attach_volume_to_server(server, self.cinder.SWAP_OLD_VOL)

        # 0. volume_attach-start
        # 1. volume_attach-end
        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-volume_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-volume_attach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_rescue_unrescue_server(self, server):
        # Both "rescue" and "unrescue" notification asserts are made here
        # rescue notification asserts
        post = {
            "rescue": {
                "rescue_image_ref": 'a2459075-d96c-40d5-893e-577ff92e721c'
            }
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'RESCUE')

        # 0. instance.rescue.start
        # 1. instance.exists
        # 2. instance.rescue.end
        self.assertEqual(3, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-rescue-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-rescue-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[2])
        self.notifier.reset()

        # unrescue notification asserts
        post = {
            'unrescue': None
        }
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(server, 'ACTIVE')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-unrescue-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-unrescue-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_soft_delete_server(self, server):
        self.flags(reclaim_instance_interval=30)
        self.api.delete_server(server['id'])
        self._wait_for_state_change(server, 'SOFT_DELETED')

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-soft_delete-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-soft_delete-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])
        self.flags(reclaim_instance_interval=0)
        # Leave instance in normal, active state
        self.api.post_server_action(server['id'], {'restore': {}})

    def _test_attach_volume_error(self, server):
        def attach_volume(*args, **kwargs):
            raise exception.CinderConnectionFailed(
                reason="Connection timed out")

        # Override the fixture's default implementation of this with our
        # error-generating version.
        cinder.API.attachment_update.side_effect = attach_volume

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
        self.assertLessEqual(2, len(self.notifier.versioned_notifications))
        self._verify_notification(
            'instance-volume_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'block_devices': block_devices,
                'volume_id': self.cinder.SWAP_NEW_VOL,
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])

        tb = self.notifier.versioned_notifications[1]['payload'][
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
            actual=self.notifier.versioned_notifications[1])

    def _test_interface_attach_and_detach(self, server):
        post = {
            'interfaceAttachment': {
                'net_id': fixtures.NeutronFixture.network_1['id']
            }
        }
        self.api.attach_interface(server['id'], post)
        self._wait_for_notification('instance.interface_attach.end')
        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-interface_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-interface_attach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

        self.notifier.reset()
        self.assertEqual(0, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)

        self.api.detach_interface(
            server['id'],
            fixtures.NeutronFixture.port_2['id'])
        self._wait_for_notification('instance.interface_detach.end')
        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-interface_detach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-interface_detach-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

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
        self.assertLessEqual(2, len(self.notifier.versioned_notifications))
        self._verify_notification(
            'instance-interface_attach-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])

        tb = self.notifier.versioned_notifications[1]['payload'][
            'nova_object.data']['fault']['nova_object.data']['traceback']
        self.assertIn("raise exception.InterfaceAttachFailed", tb)

        self._verify_notification(
            'instance-interface_attach-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id'],
                'fault.traceback': self.ANY},
            actual=self.notifier.versioned_notifications[1])

    def _test_lock_unlock_instance(self, server):
        self.api.post_server_action(server['id'], {'lock': {}})
        self._wait_for_server_parameter(server, {'locked': True})
        self.api.post_server_action(server['id'], {'unlock': {}})
        self._wait_for_server_parameter(server, {'locked': False})
        # Two versioned notifications are generated
        # 0. instance-lock
        # 1. instance-unlock

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-lock',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-unlock',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])

    def _test_lock_unlock_instance_with_reason(self, server):
        self.api.post_server_action(
            server['id'], {'lock': {"locked_reason": "global warming"}})
        self._wait_for_server_parameter(server, {'locked': True})
        self.api.post_server_action(server['id'], {'unlock': {}})
        self._wait_for_server_parameter(server, {'locked': False})
        # Two versioned notifications are generated
        # 0. instance-lock
        # 1. instance-unlock

        self.assertEqual(2, len(self.notifier.versioned_notifications),
                         self.notifier.versioned_notifications)
        self._verify_notification(
            'instance-lock-with-reason',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[0])
        self._verify_notification(
            'instance-unlock',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=self.notifier.versioned_notifications[1])
