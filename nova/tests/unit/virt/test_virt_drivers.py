#    Copyright 2010 OpenStack Foundation
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

from collections import deque
import sys
import traceback
from unittest import mock

import fixtures
import netaddr
import os_resource_classes as orc
import os_vif
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils
from oslo_utils import timeutils

from nova.compute import manager
from nova import conf
from nova.console import type as ctype
from nova import context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.fixtures import libvirt as fakelibvirt
from nova.tests.unit import fake_block_device
from nova.tests.unit import utils as test_utils
from nova.virt import block_device as driver_block_device
from nova.virt import event as virtevent
from nova.virt import fake
from nova.virt import hardware
from nova.virt import libvirt
from nova.virt.libvirt import imagebackend

LOG = logging.getLogger(__name__)
CONF = conf.CONF


def catch_notimplementederror(f):
    """Decorator to simplify catching drivers raising NotImplementedError

    If a particular call makes a driver raise NotImplementedError, we
    log it so that we can extract this information afterwards as needed.
    """

    def wrapped_func(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except NotImplementedError:
            frame = traceback.extract_tb(sys.exc_info()[2])[-1]
            LOG.error("%(driver)s does not implement %(method)s "
                      "required for test %(test)s",
                      {'driver': type(self.connection),
                       'method': frame[2], 'test': f.__name__})

    wrapped_func.__name__ = f.__name__
    wrapped_func.__doc__ = f.__doc__
    return wrapped_func


class _FakeDriverBackendTestCase(object):
    def _setup_fakelibvirt(self):
        # So that the _supports_direct_io does the test based
        # on the current working directory, instead of the
        # default instances_path which doesn't exist
        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)

        # Put fakelibvirt in place
        if 'libvirt' in sys.modules:
            self.saved_libvirt = sys.modules['libvirt']
        else:
            self.saved_libvirt = None

        self.useFixture(nova_fixtures.OSBrickFixture())
        self.useFixture(nova_fixtures.LibvirtImageBackendFixture())
        self.useFixture(nova_fixtures.LibvirtFixture())

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.host.Host._conn_event_thread',
            lambda *args: None))

        self.flags(rescue_image_id="2",
                   rescue_kernel_id="3",
                   rescue_ramdisk_id=None,
                   snapshots_directory='./',
                   sysinfo_serial='none',
                   group='libvirt')

        def fake_wait():
            pass

        def fake_detach_device_with_retry(_self, get_device_conf_func, device,
                                          live, *args, **kwargs):
            # Still calling detach, but instead of returning function
            # that actually checks if device is gone from XML, just continue
            # because XML never gets updated in these tests
            _self.detach_device(get_device_conf_func(device),
                                live=live)
            return fake_wait

        self.stub_out('nova.virt.libvirt.driver.LibvirtDriver.'
                      '_get_instance_disk_info_from_config',
                      lambda self, guest_config, block_device_info: [])
        self.stub_out('nova.virt.disk.api.extend', lambda image, size: None)
        self.stub_out('nova.virt.libvirt.driver.LibvirtDriver.'
                      'delete_instance_files', lambda self, instance: None)
        self.stub_out('nova.virt.libvirt.guest.Guest.detach_device_with_retry',
                      fake_detach_device_with_retry)
        self.stub_out('nova.virt.libvirt.guest.Guest.migrate',
                      lambda self, destination, migrate_uri=None,
                      migrate_disks=None, destination_xml=None, flags=0,
                      bandwidth=0: None)
        # We can't actually make a config drive v2 because ensure_tree has
        # been faked out
        self.stub_out('nova.virt.configdrive.ConfigDriveBuilder.make_drive',
                      lambda self, path: None)

    def _teardown_fakelibvirt(self):
        # Restore libvirt
        if self.saved_libvirt:
            sys.modules['libvirt'] = self.saved_libvirt

    def setUp(self):
        super(_FakeDriverBackendTestCase, self).setUp()
        # TODO(sdague): it would be nice to do this in a way that only
        # the relevant backends where replaced for tests, though this
        # should not harm anything by doing it for all backends
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self._setup_fakelibvirt()

    def tearDown(self):
        self._teardown_fakelibvirt()
        super(_FakeDriverBackendTestCase, self).tearDown()


class VirtDriverLoaderTestCase(_FakeDriverBackendTestCase, test.TestCase):
    """Test that ComputeManager can successfully load both
    old style and new style drivers and end up with the correct
    final class.
    """

    # if your driver supports being tested in a fake way, it can go here
    new_drivers = {
        'fake.FakeDriver': 'FakeDriver',
        'libvirt.LibvirtDriver': 'LibvirtDriver'
        }

    def test_load_new_drivers(self):
        for cls, driver in self.new_drivers.items():
            self.flags(compute_driver=cls)
            # NOTE(sdague) the try block is to make it easier to debug a
            # failure by knowing which driver broke
            try:
                cm = manager.ComputeManager()
            except Exception as e:
                self.fail("Couldn't load driver %s - %s" % (cls, e))

            self.assertEqual(cm.driver.__class__.__name__, driver,
                             "Couldn't load driver %s" % cls)

    @mock.patch.object(sys, 'exit', side_effect=test.TestingException())
    def test_fail_to_load_new_drivers(self, mock_exit):
        self.flags(compute_driver='nova.virt.amiga')
        self.assertRaises(test.TestingException, manager.ComputeManager)
        mock_exit.assert_called_once_with(1)


class _VirtDriverTestCase(_FakeDriverBackendTestCase):
    def setUp(self):
        super(_VirtDriverTestCase, self).setUp()

        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)
        self.connection = importutils.import_object(self.driver_module,
                                                    fake.FakeVirtAPI())
        self.ctxt = test_utils.get_test_admin_context()
        self.image_service = self.useFixture(nova_fixtures.GlanceFixture(self))
        # NOTE(dripton): resolve_driver_format does some file reading and
        # writing and chowning that complicate testing too much by requiring
        # using real directories with proper permissions.  Just stub it out
        # here; we test it in test_imagebackend.py
        self.stub_out('nova.virt.libvirt.imagebackend.Image.'
                      'resolve_driver_format',
                      imagebackend.Image._get_driver_format)
        os_vif.initialize()

    def _get_running_instance(self, obj=True):
        instance_ref = test_utils.get_test_instance(obj=obj)
        network_info = test_utils.get_test_network_info()
        network_info[0]['network']['subnets'][0]['meta']['dhcp_server'] = \
            '1.1.1.1'
        image_meta = test_utils.get_test_image_object(None, instance_ref)
        self.connection.spawn(self.ctxt, instance_ref, image_meta,
                              [], 'herp', {}, network_info=network_info)
        return instance_ref, network_info

    @catch_notimplementederror
    def test_init_host(self):
        self.connection.init_host('myhostname')

    @catch_notimplementederror
    def test_list_instances(self):
        self.connection.list_instances()

    @catch_notimplementederror
    def test_list_instance_uuids(self):
        self.connection.list_instance_uuids()

    @catch_notimplementederror
    def test_spawn(self):
        instance_ref, network_info = self._get_running_instance()
        domains = self.connection.list_instances()
        self.assertIn(instance_ref['name'], domains)

        num_instances = self.connection.get_num_instances()
        self.assertEqual(1, num_instances)

    @catch_notimplementederror
    def test_snapshot_not_running(self):
        instance_ref = test_utils.get_test_instance()
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        self.assertRaises(exception.InstanceNotRunning,
                          self.connection.snapshot,
                          self.ctxt, instance_ref, img_ref['id'],
                          lambda *args, **kwargs: None)

    @catch_notimplementederror
    def test_snapshot_running(self):
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        instance_ref, network_info = self._get_running_instance()
        self.connection.snapshot(self.ctxt, instance_ref, img_ref['id'],
                                 lambda *args, **kwargs: None)

    @catch_notimplementederror
    def test_reboot(self):
        reboot_type = "SOFT"
        instance_ref, network_info = self._get_running_instance()
        self.connection.reboot(self.ctxt, instance_ref, network_info,
                               reboot_type)

    @catch_notimplementederror
    def test_get_host_ip_addr(self):
        host_ip = self.connection.get_host_ip_addr()

        # Will raise an exception if it's not a valid IP at all
        ip = netaddr.IPAddress(host_ip)

        # For now, assume IPv4.
        self.assertEqual(ip.version, 4)

    @catch_notimplementederror
    def test_set_admin_password(self):
        instance, network_info = self._get_running_instance(obj=True)
        self.connection.set_admin_password(instance, 'p4ssw0rd')

    @catch_notimplementederror
    def test_resume_state_on_host_boot(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.resume_state_on_host_boot(self.ctxt, instance_ref,
                                                  network_info)

    @catch_notimplementederror
    def test_rescue(self):
        image_meta = objects.ImageMeta.from_dict({})
        instance_ref, network_info = self._get_running_instance()
        self.connection.rescue(self.ctxt, instance_ref, network_info,
                               image_meta, '', None)

    @catch_notimplementederror
    def test_unrescue_unrescued_instance(self):
        instance_ref, _ = self._get_running_instance()
        self.connection.unrescue(self.ctxt, instance_ref)

    @catch_notimplementederror
    @mock.patch('os.unlink')
    def test_unrescue_rescued_instance(self, mock_unlink):
        image_meta = objects.ImageMeta.from_dict({})
        instance_ref, network_info = self._get_running_instance()
        self.connection.rescue(self.ctxt, instance_ref, network_info,
                               image_meta, '', None)
        self.connection.unrescue(self.ctxt, instance_ref)

    @catch_notimplementederror
    def test_poll_rebooting_instances(self):
        instances = [self._get_running_instance()]
        self.connection.poll_rebooting_instances(10, instances)

    @catch_notimplementederror
    def test_migrate_disk_and_power_off(self):
        instance_ref, network_info = self._get_running_instance()
        flavor_ref = test_utils.get_test_flavor()
        self.connection.migrate_disk_and_power_off(
            self.ctxt, instance_ref, mock.sentinel.migration, flavor_ref,
            network_info)

    @catch_notimplementederror
    def test_power_off(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.power_off(instance_ref)

    @catch_notimplementederror
    def test_power_on_running(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.power_on(self.ctxt, instance_ref,
                                 network_info, None)

    @catch_notimplementederror
    def test_power_on_powered_off(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.power_off(instance_ref)
        self.connection.power_on(self.ctxt, instance_ref, network_info, None)

    @catch_notimplementederror
    def test_trigger_crash_dump(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.trigger_crash_dump(instance_ref)

    @catch_notimplementederror
    def test_soft_delete(self):
        instance_ref, network_info = self._get_running_instance(obj=True)
        self.connection.soft_delete(instance_ref)

    @catch_notimplementederror
    def test_restore_running(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.restore(instance_ref)

    @catch_notimplementederror
    def test_restore_soft_deleted(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.soft_delete(instance_ref)
        self.connection.restore(instance_ref)

    @catch_notimplementederror
    def test_pause(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.pause(instance_ref)

    @catch_notimplementederror
    def test_unpause_unpaused_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.unpause(instance_ref)

    @catch_notimplementederror
    def test_unpause_paused_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.pause(instance_ref)
        self.connection.unpause(instance_ref)

    @catch_notimplementederror
    def test_suspend(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.suspend(self.ctxt, instance_ref)

    @catch_notimplementederror
    def test_resume_unsuspended_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.resume(self.ctxt, instance_ref, network_info)

    @catch_notimplementederror
    def test_resume_suspended_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.suspend(self.ctxt, instance_ref)
        self.connection.resume(self.ctxt, instance_ref, network_info)

    @catch_notimplementederror
    def test_destroy_instance_nonexistent(self):
        fake_instance = test_utils.get_test_instance(obj=True)
        network_info = test_utils.get_test_network_info()
        self.connection.destroy(self.ctxt, fake_instance, network_info)

    @catch_notimplementederror
    def test_destroy_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.assertIn(instance_ref['name'],
                      self.connection.list_instances())
        self.connection.destroy(self.ctxt, instance_ref, network_info)
        self.assertNotIn(instance_ref['name'],
                         self.connection.list_instances())

    @catch_notimplementederror
    def test_get_volume_connector(self):
        result = self.connection.get_volume_connector({'id': 'fake'})
        self.assertIn('ip', result)
        self.assertIn('initiator', result)
        self.assertIn('host', result)
        return result

    @catch_notimplementederror
    def test_get_volume_connector_storage_ip(self):
        ip = 'my_ip'
        storage_ip = 'storage_ip'
        self.flags(my_block_storage_ip=storage_ip, my_ip=ip)
        result = self.connection.get_volume_connector({'id': 'fake'})
        self.assertIn('ip', result)
        self.assertIn('initiator', result)
        self.assertIn('host', result)
        self.assertEqual(storage_ip, result['ip'])

    @catch_notimplementederror
    @mock.patch('threading.Event.wait', new=mock.Mock())
    @mock.patch.object(libvirt.driver.LibvirtDriver, '_build_device_metadata',
                       return_value=objects.InstanceDeviceMetadata())
    def test_attach_detach_volume(self, _):
        instance_ref, network_info = self._get_running_instance()
        connection_info = {
            "driver_volume_type": "fake",
            "serial": "fake_serial",
            "data": {}
        }
        self.assertIsNone(
            self.connection.attach_volume(None, connection_info, instance_ref,
                                          '/dev/sda'))
        self.assertIsNone(
            self.connection.detach_volume(mock.sentinel.context,
                                          connection_info, instance_ref,
                                          '/dev/sda'))

    @catch_notimplementederror
    @mock.patch.object(libvirt.driver.LibvirtDriver, '_build_device_metadata',
                       return_value=objects.InstanceDeviceMetadata())
    def test_swap_volume(self, _):
        instance_ref, network_info = self._get_running_instance()
        self.assertIsNone(
            self.connection.attach_volume(None, {'driver_volume_type': 'fake',
                                                 'data': {}},
                                          instance_ref,
                                          '/dev/sda'))
        self.assertIsNone(
            self.connection.swap_volume(None, {'driver_volume_type': 'fake',
                                         'data': {}},
                                        {'driver_volume_type': 'fake',
                                         'data': {}},
                                        instance_ref,
                                        '/dev/sda', 2))

    @catch_notimplementederror
    @mock.patch('threading.Event.wait', new=mock.Mock())
    @mock.patch.object(libvirt.driver.LibvirtDriver, '_build_device_metadata',
                       return_value=objects.InstanceDeviceMetadata())
    def test_attach_detach_different_power_states(self, _):
        instance_ref, network_info = self._get_running_instance()
        connection_info = {
            "driver_volume_type": "fake",
            "serial": "fake_serial",
            "data": {}
        }
        self.connection.power_off(instance_ref)
        self.connection.attach_volume(None, connection_info, instance_ref,
                                      '/dev/sda')

        bdm = {
            'root_device_name': None,
            'swap': None,
            'ephemerals': [],
            'block_device_mapping': driver_block_device.convert_volumes([
                objects.BlockDeviceMapping(
                    self.ctxt,
                    **fake_block_device.FakeDbBlockDeviceDict(
                        {'id': 1, 'instance_uuid': instance_ref['uuid'],
                         'device_name': '/dev/sda',
                         'source_type': 'volume',
                         'destination_type': 'volume',
                         'delete_on_termination': False,
                         'snapshot_id': None,
                         'volume_id': 'abcdedf',
                         'volume_size': None,
                         'no_device': None
                         })),
                ])
        }
        bdm['block_device_mapping'][0]['connection_info'] = (
            {'driver_volume_type': 'fake', 'data': {}})
        with mock.patch.object(
                driver_block_device.DriverVolumeBlockDevice, 'save'):
            self.connection.power_on(
                    self.ctxt, instance_ref, network_info, bdm)
            self.connection.detach_volume(mock.sentinel.context,
                                          connection_info,
                                          instance_ref,
                                          '/dev/sda')

    @catch_notimplementederror
    def test_get_info(self):
        instance_ref, network_info = self._get_running_instance()
        info = self.connection.get_info(instance_ref)
        self.assertIsInstance(info, hardware.InstanceInfo)

    @catch_notimplementederror
    def test_get_info_for_unknown_instance(self):
        fake_instance = test_utils.get_test_instance(obj=True)
        self.assertRaises(exception.NotFound,
                          self.connection.get_info,
                          fake_instance)

    @catch_notimplementederror
    def test_get_diagnostics(self):
        instance_ref, network_info = self._get_running_instance(obj=True)
        self.connection.get_diagnostics(instance_ref)

    @catch_notimplementederror
    def test_get_instance_diagnostics(self):
        instance_ref, network_info = self._get_running_instance(obj=True)
        instance_ref['launched_at'] = timeutils.utcnow()
        self.connection.get_instance_diagnostics(instance_ref)

    @catch_notimplementederror
    def test_block_stats(self):
        instance_ref, network_info = self._get_running_instance()
        stats = self.connection.block_stats(instance_ref, 'someid')
        self.assertEqual(len(stats), 5)

    @catch_notimplementederror
    def test_get_console_output(self):
        instance_ref, network_info = self._get_running_instance()
        console_output = self.connection.get_console_output(self.ctxt,
            instance_ref)
        self.assertIsInstance(console_output, str)

    @catch_notimplementederror
    def test_get_vnc_console(self):
        instance, network_info = self._get_running_instance(obj=True)
        vnc_console = self.connection.get_vnc_console(self.ctxt, instance)
        self.assertIsInstance(vnc_console, ctype.ConsoleVNC)

    @catch_notimplementederror
    def test_get_spice_console(self):
        instance_ref, network_info = self._get_running_instance()
        spice_console = self.connection.get_spice_console(self.ctxt,
                                                          instance_ref)
        self.assertIsInstance(spice_console, ctype.ConsoleSpice)

    @catch_notimplementederror
    def test_get_rdp_console(self):
        instance_ref, network_info = self._get_running_instance()
        rdp_console = self.connection.get_rdp_console(self.ctxt, instance_ref)
        self.assertIsInstance(rdp_console, ctype.ConsoleRDP)

    @catch_notimplementederror
    def test_get_serial_console(self):
        self.flags(enabled=True, group='serial_console')
        instance_ref, network_info = self._get_running_instance()
        serial_console = self.connection.get_serial_console(self.ctxt,
                                                            instance_ref)
        self.assertIsInstance(serial_console, ctype.ConsoleSerial)

    @catch_notimplementederror
    def test_get_mks_console(self):
        instance_ref, network_info = self._get_running_instance()
        mks_console = self.connection.get_mks_console(self.ctxt,
                                                      instance_ref)
        self.assertIsInstance(mks_console, ctype.ConsoleMKS)

    @mock.patch(
        'nova.tests.fixtures.libvirt.Domain.jobStats',
        new=mock.Mock(return_value={
            'type': fakelibvirt.VIR_DOMAIN_JOB_COMPLETED}))
    def test_live_migration(self):
        instance_ref, network_info = self._get_running_instance()
        fake_context = context.RequestContext('fake', 'fake')
        migration = objects.Migration(context=fake_context, id=1)
        migrate_data = objects.LibvirtLiveMigrateData(
            migration=migration, bdms=[], block_migration=False,
            serial_listen_addr='127.0.0.1', serial_listen_ports=[1234])
        self.connection.live_migration(self.ctxt, instance_ref, 'otherhost',
                                       lambda *a, **b: None,
                                       lambda *a, **b: None,
                                       migrate_data=migrate_data)

    @catch_notimplementederror
    def test_live_migration_force_complete(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.active_migrations[instance_ref.uuid] = deque()
        self.connection.live_migration_force_complete(instance_ref)

    @catch_notimplementederror
    def test_live_migration_abort(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.live_migration_abort(instance_ref)

    @catch_notimplementederror
    def _check_available_resource_fields(self, host_status):
        keys = ['vcpus', 'memory_mb', 'local_gb', 'vcpus_used',
                'memory_mb_used', 'hypervisor_type', 'hypervisor_version',
                'hypervisor_hostname', 'cpu_info', 'disk_available_least',
                'supported_instances']
        for key in keys:
            self.assertIn(key, host_status)
        self.assertIsInstance(host_status['hypervisor_version'], int)

    @catch_notimplementederror
    def test_get_available_resource(self):
        available_resource = self.connection.get_available_resource(
                'myhostname')
        self._check_available_resource_fields(available_resource)

    @catch_notimplementederror
    def test_get_available_nodes(self):
        self.connection.get_available_nodes(False)

    @catch_notimplementederror
    def _check_host_cpu_status_fields(self, host_cpu_status):
        self.assertIn('kernel', host_cpu_status)
        self.assertIn('idle', host_cpu_status)
        self.assertIn('user', host_cpu_status)
        self.assertIn('iowait', host_cpu_status)
        self.assertIn('frequency', host_cpu_status)

    @catch_notimplementederror
    def test_get_host_cpu_stats(self):
        host_cpu_status = self.connection.get_host_cpu_stats()
        self._check_host_cpu_status_fields(host_cpu_status)

    @catch_notimplementederror
    def test_set_host_enabled(self):
        self.connection.set_host_enabled(True)

    @catch_notimplementederror
    def test_get_host_uptime(self):
        self.connection.get_host_uptime()

    @catch_notimplementederror
    def test_host_power_action_reboot(self):
        self.connection.host_power_action('reboot')

    @catch_notimplementederror
    def test_host_power_action_shutdown(self):
        self.connection.host_power_action('shutdown')

    @catch_notimplementederror
    def test_host_power_action_startup(self):
        self.connection.host_power_action('startup')

    def test_events(self):
        got_events = []

        def handler(event):
            got_events.append(event)

        self.connection.register_event_listener(handler)

        event1 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STARTED)
        event2 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_PAUSED)

        self.connection.emit_event(event1)
        self.connection.emit_event(event2)
        want_events = [event1, event2]
        self.assertEqual(want_events, got_events)

        event3 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_RESUMED)
        event4 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STOPPED)

        self.connection.emit_event(event3)
        self.connection.emit_event(event4)

        want_events = [event1, event2, event3, event4]
        self.assertEqual(want_events, got_events)

    def test_event_bad_object(self):
        # Passing in something which does not inherit
        # from virtevent.Event

        def handler(event):
            pass

        self.connection.register_event_listener(handler)

        badevent = {
            "foo": "bar"
        }

        self.assertRaises(ValueError,
                          self.connection.emit_event,
                          badevent)

    def test_event_bad_callback(self):
        # Check that if a callback raises an exception,
        # it does not propagate back out of the
        # 'emit_event' call

        def handler(event):
            raise Exception("Hit Me!")

        self.connection.register_event_listener(handler)

        event1 = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STARTED)

        self.connection.emit_event(event1)

    def test_emit_unicode_event(self):
        """Tests that we do not fail on translated unicode events."""
        started_event = virtevent.LifecycleEvent(
            "cef19ce0-0ca2-11df-855d-b19fbce37686",
            virtevent.EVENT_LIFECYCLE_STARTED)
        callback = mock.Mock()
        self.connection.register_event_listener(callback)
        with mock.patch.object(started_event, 'get_name',
                               return_value=u'\xF0\x9F\x92\xA9'):
            self.connection.emit_event(started_event)
        callback.assert_called_once_with(started_event)

    @catch_notimplementederror
    def test_get_instance_disk_info(self):
        # This should be implemented by any driver that supports live migrate.
        instance_ref, network_info = self._get_running_instance()
        self.connection.get_instance_disk_info(instance_ref,
                                               block_device_info={})

    @catch_notimplementederror
    def test_get_device_name_for_instance(self):
        instance, _ = self._get_running_instance()
        self.connection.get_device_name_for_instance(
            instance, [], mock.Mock(spec=objects.BlockDeviceMapping))

    def test_network_binding_host_id(self):
        # NOTE(jroll) self._get_running_instance calls spawn(), so we can't
        # use it to test this method. Make a simple object instead; we just
        # need instance.host.
        instance = objects.Instance(self.ctxt, host='somehost')
        self.assertEqual(instance.host,
            self.connection.network_binding_host_id(self.ctxt, instance))

    def test_get_allocation_ratio(self):
        inv = {}
        self.flags(cpu_allocation_ratio=16.1)
        self.flags(ram_allocation_ratio=1.6)
        self.flags(disk_allocation_ratio=1.1)
        expected_ratios = {
            orc.VCPU: CONF.cpu_allocation_ratio,
            orc.MEMORY_MB: CONF.ram_allocation_ratio,
            orc.DISK_GB: CONF.disk_allocation_ratio
        }
        # If conf is set, return conf
        self.assertEqual(expected_ratios,
                         self.connection._get_allocation_ratios(inv))

        self.flags(cpu_allocation_ratio=None)
        self.flags(ram_allocation_ratio=None)
        self.flags(disk_allocation_ratio=None)
        self.flags(initial_cpu_allocation_ratio=15.9)
        self.flags(initial_ram_allocation_ratio=1.4)
        self.flags(initial_disk_allocation_ratio=0.9)
        expected_ratios = {
            orc.VCPU: CONF.initial_cpu_allocation_ratio,
            orc.MEMORY_MB: CONF.initial_ram_allocation_ratio,
            orc.DISK_GB: CONF.initial_disk_allocation_ratio
        }
        # if conf is unset and inv doesn't exists, return init conf
        self.assertEqual(expected_ratios,
                         self.connection._get_allocation_ratios(inv))

        inv = {orc.VCPU: {'allocation_ratio': 3.0},
               orc.MEMORY_MB: {'allocation_ratio': 3.1},
               orc.DISK_GB: {'allocation_ratio': 3.2}}
        expected_ratios = {
            orc.VCPU: inv[orc.VCPU]['allocation_ratio'],
            orc.MEMORY_MB: inv[orc.MEMORY_MB]['allocation_ratio'],
            orc.DISK_GB: inv[orc.DISK_GB]['allocation_ratio']
        }
        # if conf is unset and inv exists, return inv
        self.assertEqual(expected_ratios,
                         self.connection._get_allocation_ratios(inv))


class AbstractDriverTestCase(_VirtDriverTestCase, test.TestCase):
    def setUp(self):
        self.driver_module = "nova.virt.driver.ComputeDriver"
        super(AbstractDriverTestCase, self).setUp()

    def test_live_migration(self):
        self.skipTest('Live migration is not implemented in the base '
                      'virt driver.')

    def test_post_claim_migrate_data(self):
        self.assertEqual(
            'fake-migrate-data',
            self.connection.post_claim_migrate_data(
                'fake-context', 'fake-instance', 'fake-migrate-data',
                'fake-claim'))


class FakeConnectionTestCase(_VirtDriverTestCase, test.TestCase):
    def setUp(self):
        self.driver_module = 'nova.virt.fake.FakeDriver'
        super(FakeConnectionTestCase, self).setUp()
        self.connection.init_host('myhostname')

    def _check_available_resource_fields(self, host_status):
        super(FakeConnectionTestCase, self)._check_available_resource_fields(
            host_status)

        hypervisor_type = host_status['hypervisor_type']
        supported_instances = host_status['supported_instances']
        try:
            # supported_instances could be JSON wrapped
            supported_instances = jsonutils.loads(supported_instances)
        except TypeError:
            pass
        self.assertTrue(any(hypervisor_type in x for x in supported_instances))


class LibvirtConnTestCase(_VirtDriverTestCase, test.TestCase):

    REQUIRES_LOCKING = True

    def setUp(self):
        # Point _VirtDriverTestCase at the right module
        self.driver_module = 'nova.virt.libvirt.LibvirtDriver'
        super(LibvirtConnTestCase, self).setUp()
        self.stub_out('nova.context.get_admin_context', lambda: self.ctxt)
        # This is needed for the live migration tests which spawn off the
        # operation for monitoring.
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())
        self.useFixture(nova_fixtures.CGroupsFixture())
        # When destroying an instance, os-vif will try to execute some commands
        # which hang tests so let's just stub out the unplug call to os-vif
        # since we don't care about it.
        self.stub_out('os_vif.unplug', lambda a, kw: None)
        self.stub_out('nova.compute.utils.get_machine_ips', lambda: [])
        self.stub_out('nova.virt.libvirt.utils.get_disk_size',
                      lambda *a, **k: 123456)
        self.stub_out('nova.virt.libvirt.utils.get_disk_backing_file',
                      lambda *a, **k: None)
        self.stub_out('nova.privsep.path.chown', lambda *a, **k: None)

    def test_init_host_image_type_rbd_force_raw_images_true(self):
        CONF.set_override('images_type', 'rbd', group='libvirt')
        CONF.set_override('force_raw_images', True)
        self.connection.init_host('myhostname')

    def test_init_host_image_type_non_rbd(self):
        CONF.set_override('images_type', 'default', group='libvirt')
        self.connection.init_host('myhostname')

    def test_init_host_raise_invalid_configuration(self):
        CONF.set_override('images_type', 'rbd', group='libvirt')
        CONF.set_override('force_raw_images', False)
        self.assertRaises(exception.InvalidConfiguration,
                          self.connection.init_host, 'myhostname')

    @mock.patch('os.unlink')
    @mock.patch('nova.virt.libvirt.utils.load_file')
    def test_unrescue_unrescued_instance(self, mock_load_file, mock_unlink):
        instance_ref, _ = self._get_running_instance()
        # fake out 'unrescue.xml'
        mock_load_file.return_value = self.connection._get_existing_domain_xml(
            instance_ref, None,
        )

        super().test_unrescue_unrescued_instance()

        self.assertIn('unrescue.xml', mock_load_file.call_args[0][0])

    def test_force_hard_reboot(self):
        self.flags(wait_soft_reboot_seconds=0, group='libvirt')
        self.test_reboot()

    def test_migrate_disk_and_power_off(self):
        # there is lack of fake stuff to execute this method. so pass.
        self.skipTest("Test nothing, but this method"
                      " needed to override superclass.")

    def test_internal_set_host_enabled(self):
        service_mock = mock.MagicMock()

        # Previous status of the service: disabled: False
        service_mock.configure_mock(disabled_reason='None',
                                    disabled=False)
        with mock.patch.object(objects.Service, "get_by_compute_host",
                               return_value=service_mock):
            self.connection._set_host_enabled(False, 'ERROR!')
            self.assertTrue(service_mock.disabled)
            self.assertEqual(service_mock.disabled_reason, 'AUTO: ERROR!')

    def test_set_host_enabled_when_auto_disabled(self):
        service_mock = mock.MagicMock()

        # Previous status of the service: disabled: True, 'AUTO: ERROR'
        service_mock.configure_mock(disabled_reason='AUTO: ERROR',
                                    disabled=True)
        with mock.patch.object(objects.Service, "get_by_compute_host",
                               return_value=service_mock):
            self.connection._set_host_enabled(True)
            self.assertFalse(service_mock.disabled)
            self.assertIsNone(service_mock.disabled_reason)

    def test_set_host_enabled_when_manually_disabled(self):
        service_mock = mock.MagicMock()

        # Previous status of the service: disabled: True, 'Manually disabled'
        service_mock.configure_mock(disabled_reason='Manually disabled',
                                    disabled=True)
        with mock.patch.object(objects.Service, "get_by_compute_host",
                               return_value=service_mock):
            self.connection._set_host_enabled(True)
            self.assertTrue(service_mock.disabled)
            self.assertEqual(service_mock.disabled_reason, 'Manually disabled')

    def test_set_host_enabled_dont_override_manually_disabled(self):
        service_mock = mock.MagicMock()

        # Previous status of the service: disabled: True, 'Manually disabled'
        service_mock.configure_mock(disabled_reason='Manually disabled',
                                    disabled=True)
        with mock.patch.object(objects.Service, "get_by_compute_host",
                               return_value=service_mock):
            self.connection._set_host_enabled(False, 'ERROR!')
            self.assertTrue(service_mock.disabled)
            self.assertEqual(service_mock.disabled_reason, 'Manually disabled')

    @catch_notimplementederror
    @mock.patch.object(libvirt.driver.LibvirtDriver, '_unplug_vifs')
    def test_unplug_vifs_with_destroy_vifs_false(self, unplug_vifs_mock):
        instance_ref, network_info = self._get_running_instance()
        self.connection.cleanup(self.ctxt, instance_ref, network_info,
                                destroy_vifs=False)
        self.assertEqual(unplug_vifs_mock.call_count, 0)

    @catch_notimplementederror
    @mock.patch.object(libvirt.driver.LibvirtDriver, '_unplug_vifs')
    def test_unplug_vifs_with_destroy_vifs_true(self, unplug_vifs_mock):
        instance_ref, network_info = self._get_running_instance()
        self.connection.cleanup(self.ctxt, instance_ref, network_info,
                                destroy_vifs=True)
        self.assertEqual(unplug_vifs_mock.call_count, 1)
        unplug_vifs_mock.assert_called_once_with(instance_ref,
                                            network_info, True)

    def test_get_device_name_for_instance(self):
        self.skipTest("Tested by the nova.tests.unit.virt.libvirt suite")

    @catch_notimplementederror
    @mock.patch('nova.utils.get_image_from_system_metadata')
    @mock.patch("nova.virt.libvirt.host.Host.has_min_version")
    def test_set_admin_password(self, ver, mock_image):
        self.flags(virt_type='kvm', group='libvirt')
        mock_image.return_value = {"properties": {
            "hw_qemu_guest_agent": "yes"}}
        instance, network_info = self._get_running_instance(obj=True)
        self.connection.set_admin_password(instance, 'p4ssw0rd')

    def test_get_volume_connector(self):
        for multipath in (True, False):
            self.flags(volume_use_multipath=multipath, group='libvirt')
            result = super(LibvirtConnTestCase,
                           self).test_get_volume_connector()
            self.assertIn('multipath', result)
            self.assertEqual(multipath, result['multipath'])
