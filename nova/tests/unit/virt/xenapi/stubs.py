# Copyright (c) 2010 Citrix Systems, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Stubouts, mocks and fixtures for the test suite."""

import pickle
import random
import sys

import fixtures
from oslo_serialization import jsonutils
import six

from nova import test
import nova.tests.unit.image.fake
from nova.virt.xenapi.client import session
from nova.virt.xenapi import fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops


def stubout_firewall_driver(stubs, conn):

    def fake_none(self, *args):
        return

    _vmops = conn._vmops
    stubs.Set(_vmops.firewall_driver, 'prepare_instance_filter', fake_none)
    stubs.Set(_vmops.firewall_driver, 'instance_filter_exists', fake_none)


def stubout_instance_snapshot(stubs):
    def fake_fetch_image(context, session, instance, name_label, image, type):
        return {'root': dict(uuid=_make_fake_vdi(), file=None),
                'kernel': dict(uuid=_make_fake_vdi(), file=None),
                'ramdisk': dict(uuid=_make_fake_vdi(), file=None)}

    stubs.Set(vm_utils, '_fetch_image', fake_fetch_image)

    def fake_wait_for_vhd_coalesce(*args):
        # TODO(sirp): Should we actually fake out the data here
        return "fakeparent", "fakebase"

    stubs.Set(vm_utils, '_wait_for_vhd_coalesce', fake_wait_for_vhd_coalesce)


def stubout_session(stubs, cls, product_version=(5, 6, 2),
                    product_brand='XenServer', **opt_args):
    """Stubs out methods from XenAPISession."""
    stubs.Set(session.XenAPISession, '_create_session',
              lambda s, url: cls(url, **opt_args))
    stubs.Set(session.XenAPISession, '_get_product_version_and_brand',
              lambda s: (product_version, product_brand))


def stubout_get_this_vm_uuid(stubs):
    def f(session):
        vms = [rec['uuid'] for ref, rec
               in six.iteritems(fake.get_all_records('VM'))
               if rec['is_control_domain']]
        return vms[0]
    stubs.Set(vm_utils, 'get_this_vm_uuid', f)


def stubout_image_service_download(stubs):
    def fake_download(*args, **kwargs):
        pass
    stubs.Set(nova.tests.unit.image.fake._FakeImageService,
        'download', fake_download)


def stubout_stream_disk(stubs):
    def fake_stream_disk(*args, **kwargs):
        pass
    stubs.Set(vm_utils, '_stream_disk', fake_stream_disk)


def stubout_determine_is_pv_objectstore(stubs):
    """Assumes VMs stu have PV kernels."""

    def f(*args):
        return False
    stubs.Set(vm_utils, '_determine_is_pv_objectstore', f)


def stubout_is_snapshot(stubs):
    """Always returns true

        xenapi fake driver does not create vmrefs for snapshots.
    """

    def f(*args):
        return True
    stubs.Set(vm_utils, 'is_snapshot', f)


def stubout_lookup_image(stubs):
    """Simulates a failure in lookup image."""
    def f(_1, _2, _3, _4):
        raise Exception("Test Exception raised by fake lookup_image")
    stubs.Set(vm_utils, 'lookup_image', f)


def stubout_fetch_disk_image(stubs, raise_failure=False):
    """Simulates a failure in fetch image_glance_disk."""

    def _fake_fetch_disk_image(context, session, instance, name_label, image,
                               image_type):
        if raise_failure:
            raise fake.Failure("Test Exception raised by "
                               "fake fetch_image_glance_disk")
        elif image_type == vm_utils.ImageType.KERNEL:
            filename = "kernel"
        elif image_type == vm_utils.ImageType.RAMDISK:
            filename = "ramdisk"
        else:
            filename = "unknown"

        vdi_type = vm_utils.ImageType.to_string(image_type)
        return {vdi_type: dict(uuid=None, file=filename)}

    stubs.Set(vm_utils, '_fetch_disk_image', _fake_fetch_disk_image)


def stubout_create_vm(stubs):
    """Simulates a failure in create_vm."""

    def f(*args):
        raise fake.Failure("Test Exception raised by fake create_vm")
    stubs.Set(vm_utils, 'create_vm', f)


def stubout_attach_disks(stubs):
    """Simulates a failure in _attach_disks."""

    def f(*args):
        raise fake.Failure("Test Exception raised by fake _attach_disks")
    stubs.Set(vmops.VMOps, '_attach_disks', f)


def _make_fake_vdi():
    sr_ref = fake.get_all('SR')[0]
    vdi_ref = fake.create_vdi('', sr_ref)
    vdi_rec = fake.get_record('VDI', vdi_ref)
    return vdi_rec['uuid']


class FakeSessionForVMTests(fake.SessionBase):
    """Stubs out a XenAPISession for VM tests."""

    _fake_iptables_save_output = ("# Generated by iptables-save v1.4.10 on "
                                  "Sun Nov  6 22:49:02 2011\n"
                                  "*filter\n"
                                  ":INPUT ACCEPT [0:0]\n"
                                  ":FORWARD ACCEPT [0:0]\n"
                                  ":OUTPUT ACCEPT [0:0]\n"
                                  "COMMIT\n"
                                  "# Completed on Sun Nov  6 22:49:02 2011\n")

    def host_call_plugin(self, _1, _2, plugin, method, _5):
        if plugin == 'glance' and method in ('download_vhd', 'download_vhd2'):
            root_uuid = _make_fake_vdi()
            return pickle.dumps(dict(root=dict(uuid=root_uuid)))
        elif (plugin, method) == ("xenhost", "iptables_config"):
            return fake.as_json(out=self._fake_iptables_save_output,
                                err='')
        else:
            return (super(FakeSessionForVMTests, self).
                    host_call_plugin(_1, _2, plugin, method, _5))

    def VM_start(self, _1, ref, _2, _3):
        vm = fake.get_record('VM', ref)
        if vm['power_state'] != 'Halted':
            raise fake.Failure(['VM_BAD_POWER_STATE', ref, 'Halted',
                                vm['power_state']])
        vm['power_state'] = 'Running'
        vm['is_a_template'] = False
        vm['is_control_domain'] = False
        vm['domid'] = random.randrange(1, 1 << 16)
        return vm

    def VM_start_on(self, _1, vm_ref, host_ref, _2, _3):
        vm_rec = self.VM_start(_1, vm_ref, _2, _3)
        vm_rec['resident_on'] = host_ref

    def VDI_snapshot(self, session_ref, vm_ref, _1):
        sr_ref = "fakesr"
        return fake.create_vdi('fakelabel', sr_ref, read_only=True)

    def SR_scan(self, session_ref, sr_ref):
        pass


class FakeSessionForFirewallTests(FakeSessionForVMTests):
    """Stubs out a XenApi Session for doing IPTable Firewall tests."""

    def __init__(self, uri, test_case=None):
        super(FakeSessionForFirewallTests, self).__init__(uri)
        if hasattr(test_case, '_in_rules'):
            self._in_rules = test_case._in_rules
        if hasattr(test_case, '_in6_filter_rules'):
            self._in6_filter_rules = test_case._in6_filter_rules
        self._test_case = test_case

    def host_call_plugin(self, _1, _2, plugin, method, args):
        """Mock method four host_call_plugin to be used in unit tests
           for the dom0 iptables Firewall drivers for XenAPI

        """
        if plugin == "xenhost" and method == "iptables_config":
            # The command to execute is a json-encoded list
            cmd_args = args.get('cmd_args', None)
            cmd = jsonutils.loads(cmd_args)
            if not cmd:
                ret_str = ''
            else:
                output = ''
                process_input = args.get('process_input', None)
                if cmd == ['ip6tables-save', '-c']:
                    output = '\n'.join(self._in6_filter_rules)
                if cmd == ['iptables-save', '-c']:
                    output = '\n'.join(self._in_rules)
                if cmd == ['iptables-restore', '-c', ]:
                    lines = process_input.split('\n')
                    if '*filter' in lines:
                        if self._test_case is not None:
                            self._test_case._out_rules = lines
                        output = '\n'.join(lines)
                if cmd == ['ip6tables-restore', '-c', ]:
                    lines = process_input.split('\n')
                    if '*filter' in lines:
                        output = '\n'.join(lines)
                ret_str = fake.as_json(out=output, err='')
            return ret_str
        else:
            return (super(FakeSessionForVMTests, self).
                    host_call_plugin(_1, _2, plugin, method, args))


def stub_out_vm_methods(stubs):
    def fake_acquire_bootlock(self, vm):
        pass

    def fake_release_bootlock(self, vm):
        pass

    def fake_generate_ephemeral(*args):
        pass

    def fake_wait_for_device(dev):
        pass

    stubs.Set(vmops.VMOps, "_acquire_bootlock", fake_acquire_bootlock)
    stubs.Set(vmops.VMOps, "_release_bootlock", fake_release_bootlock)
    stubs.Set(vm_utils, 'generate_ephemeral', fake_generate_ephemeral)
    stubs.Set(vm_utils, '_wait_for_device', fake_wait_for_device)


class ReplaceModule(fixtures.Fixture):
    """Replace a module with a fake module."""

    def __init__(self, name, new_value):
        self.name = name
        self.new_value = new_value

    def _restore(self, old_value):
        sys.modules[self.name] = old_value

    def setUp(self):
        super(ReplaceModule, self).setUp()
        old_value = sys.modules.get(self.name)
        sys.modules[self.name] = self.new_value
        self.addCleanup(self._restore, old_value)


class FakeSessionForVolumeTests(fake.SessionBase):
    """Stubs out a XenAPISession for Volume tests."""
    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        valid_vdi = False
        refs = fake.get_all('VDI')
        for ref in refs:
            rec = fake.get_record('VDI', ref)
            if rec['uuid'] == uuid:
                valid_vdi = True
        if not valid_vdi:
            raise fake.Failure([['INVALID_VDI', 'session', self._session]])


class FakeSessionForVolumeFailedTests(FakeSessionForVolumeTests):
    """Stubs out a XenAPISession for Volume tests: it injects failures."""
    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        # This is for testing failure
        raise fake.Failure([['INVALID_VDI', 'session', self._session]])

    def PBD_unplug(self, _1, ref):
        rec = fake.get_record('PBD', ref)
        rec['currently-attached'] = False

    def SR_forget(self, _1, ref):
        pass


def stub_out_migration_methods(stubs):
    fakesr = fake.create_sr()

    def fake_import_all_migrated_disks(session, instance, import_root=True):
        vdi_ref = fake.create_vdi(instance['name'], fakesr)
        vdi_rec = fake.get_record('VDI', vdi_ref)
        vdi_rec['other_config']['nova_disk_type'] = 'root'
        return {"root": {'uuid': vdi_rec['uuid'], 'ref': vdi_ref},
                "ephemerals": {}}

    def fake_wait_for_instance_to_start(self, *args):
        pass

    def fake_get_vdi(session, vm_ref, userdevice='0'):
        vdi_ref_parent = fake.create_vdi('derp-parent', fakesr)
        vdi_rec_parent = fake.get_record('VDI', vdi_ref_parent)
        vdi_ref = fake.create_vdi('derp', fakesr,
                sm_config={'vhd-parent': vdi_rec_parent['uuid']})
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
        return vdi_ref, vdi_rec

    def fake_sr(session, *args):
        return fakesr

    def fake_get_sr_path(*args):
        return "fake"

    def fake_destroy(*args, **kwargs):
        pass

    def fake_generate_ephemeral(*args):
        pass

    stubs.Set(vmops.VMOps, '_destroy', fake_destroy)
    stubs.Set(vmops.VMOps, '_wait_for_instance_to_start',
              fake_wait_for_instance_to_start)
    stubs.Set(vm_utils, 'import_all_migrated_disks',
              fake_import_all_migrated_disks)
    stubs.Set(vm_utils, 'scan_default_sr', fake_sr)
    stubs.Set(vm_utils, 'get_vdi_for_vm_safely', fake_get_vdi)
    stubs.Set(vm_utils, 'get_sr_path', fake_get_sr_path)
    stubs.Set(vm_utils, 'generate_ephemeral', fake_generate_ephemeral)


class FakeSessionForFailedMigrateTests(FakeSessionForVMTests):
    def VM_assert_can_migrate(self, session, vmref, migrate_data,
                              live, vdi_map, vif_map, options):
        raise fake.Failure("XenAPI VM.assert_can_migrate failed")

    def host_migrate_receive(self, session, hostref, networkref, options):
        raise fake.Failure("XenAPI host.migrate_receive failed")

    def VM_migrate_send(self, session, vmref, migrate_data, islive, vdi_map,
                        vif_map, options):
        raise fake.Failure("XenAPI VM.migrate_send failed")


# FIXME(sirp): XenAPITestBase is deprecated, all tests should be converted
# over to use XenAPITestBaseNoDB
class XenAPITestBase(test.TestCase):
    def setUp(self):
        super(XenAPITestBase, self).setUp()
        self.useFixture(ReplaceModule('XenAPI', fake))
        fake.reset()


class XenAPITestBaseNoDB(test.NoDBTestCase):
    def setUp(self):
        super(XenAPITestBaseNoDB, self).setUp()
        self.useFixture(ReplaceModule('XenAPI', fake))
        fake.reset()
