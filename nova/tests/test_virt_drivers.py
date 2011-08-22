# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 OpenStack LLC
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
import netaddr
import sys
import traceback

from nova import exception
from nova import flags
from nova import image
from nova import log as logging
from nova import test
from nova.tests import utils as test_utils

libvirt = None
FLAGS = flags.FLAGS

LOG = logging.getLogger('nova.tests.test_virt_drivers')


def catch_notimplementederror(f):
    """Decorator to simplify catching drivers raising NotImplementedError

    If a particular call makes a driver raise NotImplementedError, we
    log it so that we can extract this information afterwards to
    automatically generate a hypervisor/feature support matrix."""
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


class _VirtDriverTestCase(test.TestCase):
    def setUp(self):
        super(_VirtDriverTestCase, self).setUp()
        self.connection = self.driver_module.get_connection('')
        self.ctxt = test_utils.get_test_admin_context()
        self.image_service = image.get_default_image_service()

    @catch_notimplementederror
    def test_init_host(self):
        self.connection.init_host('myhostname')

    @catch_notimplementederror
    def test_list_instances(self):
        self.connection.list_instances()

    @catch_notimplementederror
    def test_list_instances_detail(self):
        self.connection.list_instances_detail()

    @catch_notimplementederror
    def test_spawn(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)

        domains = self.connection.list_instances()
        self.assertIn(instance_ref['name'], domains)

        domains_details = self.connection.list_instances_detail()
        self.assertIn(instance_ref['name'], [i.name for i in domains_details])

    @catch_notimplementederror
    def test_snapshot_not_running(self):
        instance_ref = test_utils.get_test_instance()
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        self.assertRaises(exception.InstanceNotRunning,
                          self.connection.snapshot,
                          self.ctxt, instance_ref, img_ref['id'])

    @catch_notimplementederror
    def test_snapshot_running(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        img_ref = self.image_service.create(self.ctxt, {'name': 'snap-1'})
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.snapshot(self.ctxt, instance_ref, img_ref['id'])

    @catch_notimplementederror
    def test_reboot(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.reboot(instance_ref, network_info)

    @catch_notimplementederror
    def test_get_host_ip_addr(self):
        host_ip = self.connection.get_host_ip_addr()

        # Will raise an exception if it's not a valid IP at all
        ip = netaddr.IPAddress(host_ip)

        # For now, assume IPv4.
        self.assertEquals(ip.version, 4)

    @catch_notimplementederror
    def test_resize_running(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.resize(instance_ref, 7)

    @catch_notimplementederror
    def test_set_admin_password(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.set_admin_password(instance_ref, 'p4ssw0rd')

    @catch_notimplementederror
    def test_inject_file(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.inject_file(instance_ref,
                                    base64.b64encode('/testfile'),
                                    base64.b64encode('testcontents'))

    @catch_notimplementederror
    def test_agent_update(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.agent_update(instance_ref, 'http://www.openstack.org/',
                                     'd41d8cd98f00b204e9800998ecf8427e')

    @catch_notimplementederror
    def test_rescue(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.rescue(self.ctxt, instance_ref,
                               lambda x: None, network_info)

    @catch_notimplementederror
    def test_unrescue_unrescued_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.unrescue(instance_ref, lambda x: None, network_info)

    @catch_notimplementederror
    def test_unrescue_rescued_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.rescue(self.ctxt, instance_ref,
                               lambda x: None, network_info)
        self.connection.unrescue(instance_ref, lambda x: None, network_info)

    @catch_notimplementederror
    def test_poll_rescued_instances(self):
        self.connection.poll_rescued_instances(10)

    @catch_notimplementederror
    def test_migrate_disk_and_power_off(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.migrate_disk_and_power_off(instance_ref, 'dest_host')

    @catch_notimplementederror
    def test_pause(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.pause(instance_ref, None)

    @catch_notimplementederror
    def test_unpause_unpaused_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.unpause(instance_ref, None)

    @catch_notimplementederror
    def test_unpause_paused_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.pause(instance_ref, None)
        self.connection.unpause(instance_ref, None)

    @catch_notimplementederror
    def test_suspend(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.suspend(instance_ref, None)

    @catch_notimplementederror
    def test_resume_unsuspended_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.resume(instance_ref, None)

    @catch_notimplementederror
    def test_resume_suspended_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.suspend(instance_ref, None)
        self.connection.resume(instance_ref, None)

    @catch_notimplementederror
    def test_destroy_instance_nonexistant(self):
        fake_instance = {'id': 42, 'name': 'I just made this up!'}
        network_info = test_utils.get_test_network_info()
        self.connection.destroy(fake_instance, network_info)

    @catch_notimplementederror
    def test_destroy_instance(self):
        instance_ref = test_utils.get_test_instance()
        network_info = test_utils.get_test_network_info()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.assertIn(instance_ref['name'],
                      self.connection.list_instances())
        self.connection.destroy(instance_ref, network_info)
        self.assertNotIn(instance_ref['name'],
                         self.connection.list_instances())

    @catch_notimplementederror
    def test_attach_detach_volume(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.attach_volume(instance_ref['name'],
                                      '/dev/null', '/mnt/nova/something')
        self.connection.detach_volume(instance_ref['name'],
                                      '/mnt/nova/something')

    @catch_notimplementederror
    def test_get_info(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        info = self.connection.get_info(instance_ref['name'])
        self.assertIn('state', info)
        self.assertIn('max_mem', info)
        self.assertIn('mem', info)
        self.assertIn('num_cpu', info)
        self.assertIn('cpu_time', info)

    @catch_notimplementederror
    def test_get_info_for_unknown_instance(self):
        self.assertRaises(exception.NotFound,
                          self.connection.get_info, 'I just made this name up')

    @catch_notimplementederror
    def test_get_diagnostics(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.get_diagnostics(instance_ref['name'])

    @catch_notimplementederror
    def test_list_disks(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.list_disks(instance_ref['name'])

    @catch_notimplementederror
    def test_list_interfaces(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.list_interfaces(instance_ref['name'])

    @catch_notimplementederror
    def test_block_stats(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        stats = self.connection.block_stats(instance_ref['name'], 'someid')
        self.assertEquals(len(stats), 5)

    @catch_notimplementederror
    def test_interface_stats(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        stats = self.connection.interface_stats(instance_ref['name'], 'someid')
        self.assertEquals(len(stats), 8)

    @catch_notimplementederror
    def test_get_console_output(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        console_output = self.connection.get_console_output(instance_ref)
        self.assertTrue(isinstance(console_output, basestring))

    @catch_notimplementederror
    def test_get_ajax_console(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        ajax_console = self.connection.get_ajax_console(instance_ref)
        self.assertIn('token', ajax_console)
        self.assertIn('host', ajax_console)
        self.assertIn('port', ajax_console)

    @catch_notimplementederror
    def test_get_vnc_console(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        vnc_console = self.connection.get_vnc_console(instance_ref)
        self.assertIn('token', vnc_console)
        self.assertIn('host', vnc_console)
        self.assertIn('port', vnc_console)

    @catch_notimplementederror
    def test_get_console_pool_info(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        console_pool = self.connection.get_console_pool_info(instance_ref)
        self.assertIn('address', console_pool)
        self.assertIn('username', console_pool)
        self.assertIn('password', console_pool)

    @catch_notimplementederror
    def test_refresh_security_group_rules(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        # FIXME: Create security group and add the instance to it
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.refresh_security_group_rules(1)

    @catch_notimplementederror
    def test_refresh_security_group_members(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        # FIXME: Create security group and add the instance to it
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.refresh_security_group_members(1)

    @catch_notimplementederror
    def test_refresh_provider_fw_rules(self):
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.refresh_provider_fw_rules()

    @catch_notimplementederror
    def test_update_available_resource(self):
        self.compute = self.start_service('compute', host='dummy')
        self.connection.update_available_resource(self.ctxt, 'dummy')

    @catch_notimplementederror
    def test_compare_cpu(self):
        cpu_info = '''{ "topology": {
                               "sockets": 1,
                               "cores": 2,
                               "threads": 1 },
                        "features": [
                            "xtpr",
                            "tm2",
                            "est",
                            "vmx",
                            "ds_cpl",
                            "monitor",
                            "pbe",
                            "tm",
                            "ht",
                            "ss",
                            "acpi",
                            "ds",
                            "vme"],
                        "arch": "x86_64",
                        "model": "Penryn",
                        "vendor": "Intel" }'''

        self.connection.compare_cpu(cpu_info)

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
        network_info = test_utils.get_test_network_info()
        instance_ref = test_utils.get_test_instance()
        self.connection.spawn(self.ctxt, instance_ref, network_info)
        self.connection.live_migration(self.ctxt, instance_ref, 'otherhost',
                                       None, None)

    @catch_notimplementederror
    def _check_host_status_fields(self, host_status):
        self.assertIn('host_name-description', host_status)
        self.assertIn('host_hostname', host_status)
        self.assertIn('host_memory_total', host_status)
        self.assertIn('host_memory_overhead', host_status)
        self.assertIn('host_memory_free', host_status)
        self.assertIn('host_memory_free_computed', host_status)
        self.assertIn('host_other_config', host_status)
        self.assertIn('host_ip_address', host_status)
        self.assertIn('host_cpu_info', host_status)
        self.assertIn('disk_available', host_status)
        self.assertIn('disk_total', host_status)
        self.assertIn('disk_used', host_status)
        self.assertIn('host_uuid', host_status)
        self.assertIn('host_name_label', host_status)

    @catch_notimplementederror
    def test_update_host_status(self):
        host_status = self.connection.update_host_status()
        self._check_host_status_fields(host_status)

    @catch_notimplementederror
    def test_get_host_stats(self):
        host_status = self.connection.get_host_stats()
        self._check_host_status_fields(host_status)

    @catch_notimplementederror
    def test_set_host_enabled(self):
        self.connection.set_host_enabled('a useless argument?', True)

    @catch_notimplementederror
    def test_host_power_action_reboot(self):
        self.connection.host_power_action('a useless argument?', 'reboot')

    @catch_notimplementederror
    def test_host_power_action_shutdown(self):
        self.connection.host_power_action('a useless argument?', 'shutdown')

    @catch_notimplementederror
    def test_host_power_action_startup(self):
        self.connection.host_power_action('a useless argument?', 'startup')


class AbstractDriverTestCase(_VirtDriverTestCase):
    def setUp(self):
        import nova.virt.driver

        self.driver_module = nova.virt.driver

        def get_driver_connection(_):
            return nova.virt.driver.ComputeDriver()

        self.driver_module.get_connection = get_driver_connection
        super(AbstractDriverTestCase, self).setUp()


class FakeConnectionTestCase(_VirtDriverTestCase):
    def setUp(self):
        import nova.virt.fake
        self.driver_module = nova.virt.fake
        super(FakeConnectionTestCase, self).setUp()

# Before long, we'll add the real hypervisor drivers here as well
# with whatever instrumentation they need to work independently of
# their hypervisor. This way, we can verify that they all act the
# same.
