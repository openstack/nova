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

from nova import context
from nova import exception
from nova.tests import fixtures
from nova.tests.functional.notification_sample_tests \
    import notification_sample_base
from nova.tests.unit import fake_notifier


class TestInstanceNotificationSample(
        notification_sample_base.NotificationSampleTestBase):

    def setUp(self):
        self.flags(use_neutron=True)
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

    def _wait_until_swap_volume_error(self):
        for i in range(50):
            if self.cinder.swap_error:
                return
            time.sleep(0.5)
        self.fail("Timed out waiting for volume swap error to occur.")

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

        actions = [
            self._test_power_off_on_server,
            self._test_restore_server,
            self._test_suspend_resume_server,
            self._test_pause_unpause_server,
            self._test_shelve_server,
            self._test_shelve_offload_server,
            self._test_unshelve_server,
            self._test_resize_server,
            self._test_revert_server,
            self._test_resize_confirm_server,
            self._test_snapshot_server,
            self._test_rebuild_server,
            self._test_reboot_server,
            self._test_reboot_server_error,
            self._test_trigger_crash_dump,
            self._test_volume_attach_detach_server,
            self._test_rescue_server,
            self._test_unrescue_server,
            self._test_soft_delete_server,
            self._test_attach_volume_error,
        ]

        for action in actions:
            fake_notifier.reset()
            action(server)
            # Ensure that instance is in active state after an action
            self._wait_for_state_change(self.admin_api, server, 'ACTIVE')

    def test_create_delete_server(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})
        self.api.delete_server(server['id'])
        self._wait_until_deleted(server)
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))

        # This list needs to be in order.
        expected_notifications = [
            'instance-create-start',
            'instance-create-end',
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

        server = self._boot_a_server(
            expected_status='ERROR',
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))

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
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

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

        instance_updates = self._wait_for_notifications('instance.update', 7)

        # The first notification comes from the nova-conductor the
        # rest is from the nova-compute. To keep the test simpler
        # assert this fact and then modify the publisher_id of the
        # first notification to match the template
        self.assertEqual('conductor:fake-mini',
                         instance_updates[0]['publisher_id'])
        instance_updates[0]['publisher_id'] = 'nova-compute:fake-mini'

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
             'state_update.old_task_state': None},

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
             'tags': ["tag1"]
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
             'tags': ["tag1"]
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
                'power_state': 'running',
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

    def _test_shelve_server(self, server):
        self.flags(shelved_offload_time = -1)

        self.api.post_server_action(server['id'], {'shelve': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHELVED')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-shelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-shelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        post = {'unshelve': None}
        self.api.post_server_action(server['id'], post)

    def _test_shelve_offload_server(self, server):
        self.flags(shelved_offload_time=-1)
        self.api.post_server_action(server['id'], {'shelve': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHELVED')
        self.api.post_server_action(server['id'], {'shelveOffload': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHELVED_OFFLOADED')

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-shelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-shelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

        self._verify_notification(
            'instance-shelve_offload-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[2])
        self._verify_notification(
            'instance-shelve_offload-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[3])

        self.api.post_server_action(server['id'], {'unshelve': None})

    def _test_unshelve_server(self, server):
        # setting the shelved_offload_time to 0 should set the
        # instance status to 'SHELVED_OFFLOADED'
        self.flags(shelved_offload_time = 0)
        self.api.post_server_action(server['id'], {'shelve': {}})
        self._wait_for_state_change(self.api, server,
                                    expected_status='SHELVED_OFFLOADED')

        post = {'unshelve': None}
        self.api.post_server_action(server['id'], post)
        self._wait_for_state_change(self.admin_api, server, 'ACTIVE')
        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-unshelve-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-unshelve-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

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

    def _test_resize_server(self, server):
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

        self.assertEqual(4, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        # This list needs to be in order.
        expected_notifications = [
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

        post = {'revertResize': None}
        self.api.post_server_action(server['id'], post)

    def _test_snapshot_server(self, server):
        post = {'createImage': {'name': 'test-snap'}}
        self.api.post_server_action(server['id'], post)
        self._wait_for_notification('instance.snapshot.end')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-snapshot-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
                    actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-snapshot-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _test_rebuild_server(self, server):
        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        # Before going back to ACTIVE state
        # server state need to be changed to REBUILD state
        self._wait_for_state_change(self.api, server,
                                    expected_status='REBUILD')
        self._wait_for_state_change(self.api, server,
                                    expected_status='ACTIVE')

        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-rebuild-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-rebuild-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    @mock.patch('nova.compute.manager.ComputeManager.'
                '_do_rebuild_instance_with_claim')
    def test_rebuild_server_exc(self, mock_rebuild):
        def _compute_resources_unavailable(*args, **kwargs):
            raise exception.ComputeResourcesUnavailable(
                reason="fake-resource")

        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})

        fake_notifier.reset()

        post = {
            'rebuild': {
                'imageRef': 'a2459075-d96c-40d5-893e-577ff92e721c',
                'metadata': {}
            }
        }
        self.api.post_server_action(server['id'], post)
        mock_rebuild.side_effect = _compute_resources_unavailable
        self._wait_for_state_change(self.api, server, expected_status='ERROR')
        self.assertEqual(2, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-rebuild-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])

    def _test_restore_server(self, server):
        self.flags(reclaim_instance_interval=30)
        self.api.delete_server(server['id'])
        self._wait_for_state_change(self.api, server, 'SOFT_DELETED')
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

        self.flags(reclaim_instance_interval=0)

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
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])

    def _attach_volume_to_server(self, server, volume_id):
        self.api.post_server_volume(
            server['id'], {"volumeAttachment": {"volumeId": volume_id}})
        self._wait_for_notification('instance.volume_attach.end')

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

        self.assertEqual(6, len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-volume_swap-start',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-volume_swap-end',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    def test_volume_swap_server_with_error(self):
        server = self._boot_a_server(
            extra_params={'networks': [{'port': self.neutron.port_1['id']}]})

        self._attach_volume_to_server(server, self.cinder.SWAP_ERR_OLD_VOL)
        self.cinder.swap_volume_instance_error_uuid = server['id']

        self._volume_swap_server(server, self.cinder.SWAP_ERR_OLD_VOL,
                                 self.cinder.SWAP_ERR_NEW_VOL)
        self._wait_until_swap_volume_error()

        # Seven versioned notifications are generated. We only rely on the
        # first six because _wait_until_swap_volume_error will return True
        # after volume_api.unreserve is called on the cinder fixture, and that
        # happens before the instance fault is handled in the compute manager
        # which generates the last notification (compute.exception).
        # 0. instance-create-start
        # 1. instance-create-end
        # 2. instance-volume_attach-start
        # 3. instance-volume_attach-end
        # 4. instance-volume_swap-start
        # 5. instance-volume_swap-error
        # 6. compute.exception
        self.assertTrue(len(fake_notifier.VERSIONED_NOTIFICATIONS) >= 6,
                        'Unexpected number of versioned notifications. '
                        'Expected at least 6, got: %s' %
                        len(fake_notifier.VERSIONED_NOTIFICATIONS))
        self._verify_notification(
            'instance-volume_swap-start',
            replacements={
                'new_volume_id': self.cinder.SWAP_ERR_NEW_VOL,
                'old_volume_id': self.cinder.SWAP_ERR_OLD_VOL,
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[4])
        self._verify_notification(
            'instance-volume_swap-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[5])

    def _test_revert_server(self, server):
        pass

    def _test_resize_confirm_server(self, server):
        pass

    def _test_trigger_crash_dump(self, server):
        pass

    def _test_volume_attach_detach_server(self, server):
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

        fake_notifier.reset()
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

    def _test_rescue_server(self, server):
        pass

    def _test_unrescue_server(self, server):
        pass

    def _test_soft_delete_server(self, server):
        pass

    @mock.patch('nova.volume.cinder.API.attach')
    def _test_attach_volume_error(self, server, mock_attach):
        def attach_volume(*args, **kwargs):
            raise exception.CinderConnectionFailed(
                reason="Connection timed out")
        mock_attach.side_effect = attach_volume

        post = {"volumeAttachment": {"volumeId": self.cinder.SWAP_OLD_VOL}}
        self.api.post_server_volume(server['id'], post)

        self._wait_for_notification('instance.volume_attach.error')

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
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[0])
        self._verify_notification(
            'instance-volume_attach-error',
            replacements={
                'reservation_id': server['reservation_id'],
                'uuid': server['id']},
            actual=fake_notifier.VERSIONED_NOTIFICATIONS[1])
