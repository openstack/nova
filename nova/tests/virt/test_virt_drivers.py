# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
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

import base64
import fixtures
import netaddr
import sys
import traceback

from nova.compute import manager
from nova import exception
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova import test
from nova.tests.image import fake as fake_image
from nova.tests import utils as test_utils
from nova.tests.virt.libvirt import fake_libvirt_utils
from nova.virt import event as virtevent
from nova.virt import fake

LOG = logging.getLogger(__name__)


def catch_notimplementederror(f):
    """Decorator to simplify catching drivers raising NotImplementedError

    If a particular call makes a driver raise NotImplementedError, we
    log it so that we can extract this information afterwards to
    automatically generate a hypervisor/feature support matrix.
    """
    def wrapped_func(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except NotImplementedError:
            frame = traceback.extract_tb(sys.exc_info()[2])[-1]
            LOG.error('%(driver)s does not implement %(method)s' % {
                                               'driver': type(self.connection),
                                               'method': frame[2]})

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

        import nova.tests.virt.libvirt.fake_imagebackend as fake_imagebackend
        import nova.tests.virt.libvirt.fake_libvirt_utils as fake_libvirt_utils
        import nova.tests.virt.libvirt.fakelibvirt as fakelibvirt

        sys.modules['libvirt'] = fakelibvirt
        import nova.virt.libvirt.driver
        import nova.virt.libvirt.firewall

        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.imagebackend',
            fake_imagebackend))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.libvirt',
            fakelibvirt))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.libvirt_utils',
            fake_libvirt_utils))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.libvirt_utils',
            fake_libvirt_utils))
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.firewall.libvirt',
            fakelibvirt))

        self.flags(rescue_image_id="2",
                   rescue_kernel_id="3",
                   rescue_ramdisk_id=None,
                   libvirt_snapshots_directory='./')

        def fake_extend(image, size):
            pass

        def fake_migrateToURI(*a):
            pass

        def fake_make_drive(_self, _path):
            pass

        def fake_get_instance_disk_info(_self, instance, xml=None,
                                        block_device_info=None):
            return '[]'

        def fake_delete_instance_files(_self, _instance):
            pass

        self.stubs.Set(nova.virt.libvirt.driver.LibvirtDriver,
                       'get_instance_disk_info',
                       fake_get_instance_disk_info)

        self.stubs.Set(nova.virt.libvirt.driver.disk,
                       'extend', fake_extend)

        self.stubs.Set(nova.virt.libvirt.driver.LibvirtDriver,
                       '_delete_instance_files',
                       fake_delete_instance_files)

        # Like the existing fakelibvirt.migrateToURI, do nothing,
        # but don't fail for these tests.
        self.stubs.Set(nova.virt.libvirt.driver.libvirt.Domain,
                       'migrateToURI', fake_migrateToURI)

        # We can't actually make a config drive v2 because ensure_tree has
        # been faked out
        self.stubs.Set(nova.virt.configdrive.ConfigDriveBuilder,
                       'make_drive', fake_make_drive)

    def _teardown_fakelibvirt(self):
        # Restore libvirt
        if self.saved_libvirt:
            sys.modules['libvirt'] = self.saved_libvirt

    def setUp(self):
        super(_FakeDriverBackendTestCase, self).setUp()
        # TODO(sdague): it would be nice to do this in a way that only
        # the relevant backends where replaced for tests, though this
        # should not harm anything by doing it for all backends
        fake_image.stub_out_image_service(self.stubs)
        self._setup_fakelibvirt()

    def tearDown(self):
        fake_image.FakeImageService_reset()
        self._teardown_fakelibvirt()
        super(_FakeDriverBackendTestCase, self).tearDown()


class VirtDriverLoaderTestCase(_FakeDriverBackendTestCase, test.TestCase):
    """Test that ComputeManager can successfully load both
    old style and new style drivers and end up with the correct
    final class.
    """

    # if your driver supports being tested in a fake way, it can go here
    #
    # both long form and short form drivers are supported
    new_drivers = {
        'nova.virt.fake.FakeDriver': 'FakeDriver',
        'nova.virt.libvirt.LibvirtDriver': 'LibvirtDriver',
        'fake.FakeDriver': 'FakeDriver',
        'libvirt.LibvirtDriver': 'LibvirtDriver'
        }

    def test_load_new_drivers(self):
        for cls, driver in self.new_drivers.iteritems():
            self.flags(compute_driver=cls)
            # NOTE(sdague) the try block is to make it easier to debug a
            # failure by knowing which driver broke
            try:
                cm = manager.ComputeManager()
            except Exception as e:
                self.fail("Couldn't load driver %s - %s" % (cls, e))

            self.assertEqual(cm.driver.__class__.__name__, driver,
                             "Could't load driver %s" % cls)

    def test_fail_to_load_new_drivers(self):
        self.flags(compute_driver='nova.virt.amiga')

        def _fake_exit(error):
            raise test.TestingException()

        self.stubs.Set(sys, 'exit', _fake_exit)
        self.assertRaises(test.TestingException, manager.ComputeManager)


class _VirtDriverTestCase(_FakeDriverBackendTestCase):
    def setUp(self):
        super(_VirtDriverTestCase, self).setUp()

        self.flags(instances_path=self.useFixture(fixtures.TempDir()).path)
        self.connection = importutils.import_object(self.driver_module,
                                                    fake.FakeVirtAPI())
        self.ctxt = test_utils.get_test_admin_context()
        self.image_service = fake_image.FakeImageService()

    def _get_running_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        image_info = test_utils.get_test_image_info(None, instance_ref)
        self.connection.spawn(self.ctxt, instance_ref, image_info,
                              [], 'herp', network_info=network_info)
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
    def test_live_snapshot_not_running(self):
        instance_ref = test_utils.get_test_instance()
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        self.assertRaises(exception.InstanceNotRunning,
                          self.connection.live_snapshot,
                          self.ctxt, instance_ref, img_ref['id'],
                          lambda *args, **kwargs: None)

    @catch_notimplementederror
    def test_live_snapshot_running(self):
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        instance_ref, network_info = self._get_running_instance()
        self.connection.live_snapshot(self.ctxt, instance_ref, img_ref['id'],
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
        self.assertEquals(ip.version, 4)

    @catch_notimplementederror
    def test_set_admin_password(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.set_admin_password(instance_ref, 'p4ssw0rd')

    @catch_notimplementederror
    def test_inject_file(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.inject_file(instance_ref,
                                    base64.b64encode('/testfile'),
                                    base64.b64encode('testcontents'))

    @catch_notimplementederror
    def test_resume_state_on_host_boot(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.resume_state_on_host_boot(self.ctxt, instance_ref,
                                                  network_info)

    @catch_notimplementederror
    def test_rescue(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.rescue(self.ctxt, instance_ref, network_info, None, '')

    @catch_notimplementederror
    def test_unrescue_unrescued_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.unrescue(instance_ref, network_info)

    @catch_notimplementederror
    def test_unrescue_rescued_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.rescue(self.ctxt, instance_ref, network_info, None, '')
        self.connection.unrescue(instance_ref, network_info)

    @catch_notimplementederror
    def test_poll_rebooting_instances(self):
        instances = [self._get_running_instance()]
        self.connection.poll_rebooting_instances(10, instances)

    @catch_notimplementederror
    def test_migrate_disk_and_power_off(self):
        instance_ref, network_info = self._get_running_instance()
        instance_type_ref = test_utils.get_test_instance_type()
        self.connection.migrate_disk_and_power_off(
            self.ctxt, instance_ref, 'dest_host', instance_type_ref,
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
    def test_soft_delete(self):
        instance_ref, network_info = self._get_running_instance()
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
        self.connection.suspend(instance_ref)

    @catch_notimplementederror
    def test_resume_unsuspended_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.resume(instance_ref, network_info)

    @catch_notimplementederror
    def test_resume_suspended_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.suspend(instance_ref)
        self.connection.resume(instance_ref, network_info)

    @catch_notimplementederror
    def test_destroy_instance_nonexistent(self):
        fake_instance = {'id': 42, 'name': 'I just made this up!',
                         'uuid': 'bda5fb9e-b347-40e8-8256-42397848cb00'}
        network_info = test_utils.get_test_network_info()
        self.connection.destroy(fake_instance, network_info)

    @catch_notimplementederror
    def test_destroy_instance(self):
        instance_ref, network_info = self._get_running_instance()
        self.assertIn(instance_ref['name'],
                      self.connection.list_instances())
        self.connection.destroy(instance_ref, network_info)
        self.assertNotIn(instance_ref['name'],
                         self.connection.list_instances())

    @catch_notimplementederror
    def test_get_volume_connector(self):
        result = self.connection.get_volume_connector({'id': 'fake'})
        self.assertTrue('ip' in result)
        self.assertTrue('initiator' in result)
        self.assertTrue('host' in result)

    @catch_notimplementederror
    def test_attach_detach_volume(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.attach_volume({'driver_volume_type': 'fake'},
                                      instance_ref,
                                      '/dev/sda')
        self.connection.detach_volume({'driver_volume_type': 'fake'},
                                      instance_ref,
                                      '/dev/sda')

    @catch_notimplementederror
    def test_swap_volume(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.attach_volume({'driver_volume_type': 'fake'},
                                      instance_ref,
                                      '/dev/sda')
        self.connection.swap_volume({'driver_volume_type': 'fake'},
                                    {'driver_volume_type': 'fake'},
                                    instance_ref,
                                    '/dev/sda')

    @catch_notimplementederror
    def test_attach_detach_different_power_states(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.power_off(instance_ref)
        self.connection.attach_volume({'driver_volume_type': 'fake'},
                                      instance_ref,
                                      '/dev/sda')

        bdm = {
            'root_device_name': None,
            'swap': None,
            'ephemerals': [],
            'block_device_mapping': [{
            'instance_uuid': instance_ref['uuid'],
            'connection_info': {'driver_volume_type': 'fake'},
            'mount_device': '/dev/sda',
            'delete_on_termination': False,
            'virtual_name': None,
            'snapshot_id': None,
            'volume_id': 'abcdedf',
            'volume_size': None,
            'no_device': None
            }]
        }
        self.connection.power_on(self.ctxt, instance_ref, network_info, bdm)
        self.connection.detach_volume({'driver_volume_type': 'fake'},
                                      instance_ref,
                                      '/dev/sda')

    @catch_notimplementederror
    def test_get_info(self):
        instance_ref, network_info = self._get_running_instance()
        info = self.connection.get_info(instance_ref)
        self.assertIn('state', info)
        self.assertIn('max_mem', info)
        self.assertIn('mem', info)
        self.assertIn('num_cpu', info)
        self.assertIn('cpu_time', info)

    @catch_notimplementederror
    def test_get_info_for_unknown_instance(self):
        self.assertRaises(exception.NotFound,
                          self.connection.get_info,
                          {'name': 'I just made this name up'})

    @catch_notimplementederror
    def test_get_diagnostics(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.get_diagnostics(instance_ref)

    @catch_notimplementederror
    def test_block_stats(self):
        instance_ref, network_info = self._get_running_instance()
        stats = self.connection.block_stats(instance_ref['name'], 'someid')
        self.assertEquals(len(stats), 5)

    @catch_notimplementederror
    def test_interface_stats(self):
        instance_ref, network_info = self._get_running_instance()
        stats = self.connection.interface_stats(instance_ref['name'], 'someid')
        self.assertEquals(len(stats), 8)

    @catch_notimplementederror
    def test_get_console_output(self):
        fake_libvirt_utils.files['dummy.log'] = ''
        instance_ref, network_info = self._get_running_instance()
        console_output = self.connection.get_console_output(instance_ref)
        self.assertTrue(isinstance(console_output, basestring))

    @catch_notimplementederror
    def test_get_vnc_console(self):
        instance_ref, network_info = self._get_running_instance()
        vnc_console = self.connection.get_vnc_console(instance_ref)
        self.assertIn('internal_access_path', vnc_console)
        self.assertIn('host', vnc_console)
        self.assertIn('port', vnc_console)

    @catch_notimplementederror
    def test_get_spice_console(self):
        instance_ref, network_info = self._get_running_instance()
        spice_console = self.connection.get_spice_console(instance_ref)
        self.assertIn('internal_access_path', spice_console)
        self.assertIn('host', spice_console)
        self.assertIn('port', spice_console)
        self.assertIn('tlsPort', spice_console)

    @catch_notimplementederror
    def test_get_console_pool_info(self):
        instance_ref, network_info = self._get_running_instance()
        console_pool = self.connection.get_console_pool_info(instance_ref)
        self.assertIn('address', console_pool)
        self.assertIn('username', console_pool)
        self.assertIn('password', console_pool)

    @catch_notimplementederror
    def test_refresh_security_group_rules(self):
        # FIXME: Create security group and add the instance to it
        instance_ref, network_info = self._get_running_instance()
        self.connection.refresh_security_group_rules(1)

    @catch_notimplementederror
    def test_refresh_security_group_members(self):
        # FIXME: Create security group and add the instance to it
        instance_ref, network_info = self._get_running_instance()
        self.connection.refresh_security_group_members(1)

    @catch_notimplementederror
    def test_refresh_provider_fw_rules(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.refresh_provider_fw_rules()

    @catch_notimplementederror
    def test_ensure_filtering_for_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.ensure_filtering_rules_for_instance(instance_ref,
                                                            network_info)

    @catch_notimplementederror
    def test_unfilter_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.unfilter_instance(instance_ref, network_info)

    @catch_notimplementederror
    def test_live_migration(self):
        instance_ref, network_info = self._get_running_instance()
        self.connection.live_migration(self.ctxt, instance_ref, 'otherhost',
                                       lambda *a: None, lambda *a: None)

    @catch_notimplementederror
    def _check_host_status_fields(self, host_status):
        self.assertIn('disk_total', host_status)
        self.assertIn('disk_used', host_status)
        self.assertIn('host_memory_total', host_status)
        self.assertIn('host_memory_free', host_status)

    @catch_notimplementederror
    def test_get_host_stats(self):
        host_status = self.connection.get_host_stats()
        self._check_host_status_fields(host_status)

    @catch_notimplementederror
    def test_set_host_enabled(self):
        self.connection.set_host_enabled('a useless argument?', True)

    @catch_notimplementederror
    def test_get_host_uptime(self):
        self.connection.get_host_uptime('a useless argument?')

    @catch_notimplementederror
    def test_host_power_action_reboot(self):
        self.connection.host_power_action('a useless argument?', 'reboot')

    @catch_notimplementederror
    def test_host_power_action_shutdown(self):
        self.connection.host_power_action('a useless argument?', 'shutdown')

    @catch_notimplementederror
    def test_host_power_action_startup(self):
        self.connection.host_power_action('a useless argument?', 'startup')

    @catch_notimplementederror
    def test_add_to_aggregate(self):
        self.connection.add_to_aggregate(self.ctxt, 'aggregate', 'host')

    @catch_notimplementederror
    def test_remove_from_aggregate(self):
        self.connection.remove_from_aggregate(self.ctxt, 'aggregate', 'host')

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


class AbstractDriverTestCase(_VirtDriverTestCase, test.TestCase):
    def setUp(self):
        self.driver_module = "nova.virt.driver.ComputeDriver"
        super(AbstractDriverTestCase, self).setUp()


class FakeConnectionTestCase(_VirtDriverTestCase, test.TestCase):
    def setUp(self):
        self.driver_module = 'nova.virt.fake.FakeDriver'
        super(FakeConnectionTestCase, self).setUp()


class LibvirtConnTestCase(_VirtDriverTestCase, test.TestCase):
    def setUp(self):
        # Point _VirtDriverTestCase at the right module
        self.driver_module = 'nova.virt.libvirt.LibvirtDriver'
        super(LibvirtConnTestCase, self).setUp()

    def test_force_hard_reboot(self):
        self.flags(libvirt_wait_soft_reboot_seconds=0)
        self.test_reboot()

    def test_migrate_disk_and_power_off(self):
        # there is lack of fake stuff to execute this method. so pass.
        self.skipTest("Test nothing, but this method"
                      " needed to override superclass.")
