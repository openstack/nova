# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Stubouts, mocks and fixtures for the test suite"""

import json
import random

from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova import utils


def stubout_firewall_driver(stubs, conn):

    def fake_none(self, *args):
        return

    vmops = conn._vmops
    stubs.Set(vmops.firewall_driver, 'setup_basic_filtering', fake_none)
    stubs.Set(vmops.firewall_driver, 'prepare_instance_filter', fake_none)
    stubs.Set(vmops.firewall_driver, 'instance_filter_exists', fake_none)


def stubout_instance_snapshot(stubs):
    @classmethod
    def fake_fetch_image(cls, context, session, instance, image, user,
                         project, type):
        return [dict(vdi_type='os', vdi_uuid=_make_fake_vdi())]

    stubs.Set(vm_utils.VMHelper, 'fetch_image', fake_fetch_image)

    def fake_wait_for_vhd_coalesce(*args):
        #TODO(sirp): Should we actually fake out the data here
        return "fakeparent"

    stubs.Set(vm_utils, '_wait_for_vhd_coalesce', fake_wait_for_vhd_coalesce)


def stubout_session(stubs, cls, product_version=None, **opt_args):
    """Stubs out three methods from XenAPISession"""
    def fake_import(self):
        """Stubs out get_imported_xenapi of XenAPISession"""
        fake_module = 'nova.virt.xenapi.fake'
        from_list = ['fake']
        return __import__(fake_module, globals(), locals(), from_list, -1)

    stubs.Set(xenapi_conn.XenAPISession, '_create_session',
              lambda s, url: cls(url, **opt_args))
    stubs.Set(xenapi_conn.XenAPISession, 'get_imported_xenapi',
                       fake_import)
    if product_version is None:
        product_version = (5, 6, 2)
    stubs.Set(xenapi_conn.XenAPISession, 'get_product_version',
            lambda s: product_version)


def stub_out_get_target(stubs):
    """Stubs out _get_target in volume_utils"""
    def fake_get_target(volume_id):
        return (None, None)

    stubs.Set(volume_utils, '_get_target', fake_get_target)


def stubout_get_this_vm_uuid(stubs):
    def f():
        vms = [rec['uuid'] for ref, rec
               in fake.get_all_records('VM').iteritems()
               if rec['is_control_domain']]
        return vms[0]
    stubs.Set(vm_utils, 'get_this_vm_uuid', f)


def stubout_stream_disk(stubs):
    def f(_1, _2, _3, _4):
        pass
    stubs.Set(vm_utils, '_stream_disk', f)


def stubout_is_vdi_pv(stubs):
    def f(_1):
        return False
    stubs.Set(vm_utils, '_is_vdi_pv', f)


def stubout_determine_is_pv_objectstore(stubs):
    """Assumes VMs stu have PV kernels"""

    @classmethod
    def f(cls, *args):
        return False
    stubs.Set(vm_utils.VMHelper, '_determine_is_pv_objectstore', f)


def stubout_is_snapshot(stubs):
    """ Always returns true
        xenapi fake driver does not create vmrefs for snapshots """

    @classmethod
    def f(cls, *args):
        return True
    stubs.Set(vm_utils.VMHelper, 'is_snapshot', f)


def stubout_lookup_image(stubs):
    """Simulates a failure in lookup image."""
    def f(_1, _2, _3, _4):
        raise Exception("Test Exception raised by fake lookup_image")
    stubs.Set(vm_utils, 'lookup_image', f)


def stubout_fetch_image_glance_disk(stubs):
    """Simulates a failure in fetch image_glance_disk."""

    @classmethod
    def f(cls, *args):
        raise fake.Failure("Test Exception raised by " +
                           "fake fetch_image_glance_disk")
    stubs.Set(vm_utils.VMHelper, '_fetch_image_glance_disk', f)


def stubout_create_vm(stubs):
    """Simulates a failure in create_vm."""

    @classmethod
    def f(cls, *args):
        raise fake.Failure("Test Exception raised by " +
                           "fake create_vm")
    stubs.Set(vm_utils.VMHelper, 'create_vm', f)


def stubout_loopingcall_start(stubs):
    def fake_start(self, interval, now=True):
        self.f(*self.args, **self.kw)
    stubs.Set(utils.LoopingCall, 'start', fake_start)


def _make_fake_vdi():
    sr_ref = fake.get_all('SR')[0]
    vdi_ref = fake.create_vdi('', False, sr_ref, False)
    vdi_rec = fake.get_record('VDI', vdi_ref)
    return vdi_rec['uuid']


class FakeSessionForVMTests(fake.SessionBase):
    """ Stubs out a XenAPISession for VM tests """

    _fake_iptables_save_output = \
        "# Generated by iptables-save v1.4.10 on Sun Nov  6 22:49:02 2011\n"\
        "*filter\n"\
        ":INPUT ACCEPT [0:0]\n"\
        ":FORWARD ACCEPT [0:0]\n"\
        ":OUTPUT ACCEPT [0:0]\n"\
        "COMMIT\n"\
        "# Completed on Sun Nov  6 22:49:02 2011\n"

    def __init__(self, uri):
        super(FakeSessionForVMTests, self).__init__(uri)

    def host_call_plugin(self, _1, _2, plugin, method, _5):
        if (plugin, method) == ('glance', 'download_vhd'):
            return fake.as_json(dict(vdi_type='os',
                                     vdi_uuid=_make_fake_vdi()))
        elif (plugin, method) == ("xenhost", "iptables_config"):
            return fake.as_json(out=self._fake_iptables_save_output,
                                err='')
        else:
            return (super(FakeSessionForVMTests, self).
                    host_call_plugin(_1, _2, plugin, method, _5))

    def host_call_plugin_swap(self, _1, _2, plugin, method, _5):
        if (plugin, method) == ('glance', 'download_vhd'):
            return fake.as_json(dict(vdi_type='os',
                                     vdi_uuid=_make_fake_vdi()),
                                dict(vdi_type='swap',
                                     vdi_uuid=_make_fake_vdi()))
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

    def VM_snapshot(self, session_ref, vm_ref, label):
        status = "Running"
        template_vm_ref = fake.create_vm(label, status, is_a_template=True,
            is_control_domain=False)

        sr_ref = "fakesr"
        template_vdi_ref = fake.create_vdi(label, read_only=True,
            sr_ref=sr_ref, sharable=False)

        template_vbd_ref = fake.create_vbd(template_vm_ref, template_vdi_ref)
        return template_vm_ref

    def VDI_destroy(self, session_ref, vdi_ref):
        fake.destroy_vdi(vdi_ref)

    def VM_destroy(self, session_ref, vm_ref):
        fake.destroy_vm(vm_ref)

    def SR_scan(self, session_ref, sr_ref):
        pass

    def VDI_set_name_label(self, session_ref, vdi_ref, name_label):
        pass


class FakeSessionForFirewallTests(FakeSessionForVMTests):
    """ Stubs out a XenApi Session for doing IPTable Firewall tests """

    def __init__(self, uri, test_case=None):
        super(FakeSessionForFirewallTests, self).__init__(uri)
        if hasattr(test_case, '_in_filter_rules'):
            self._in_filter_rules = test_case._in_filter_rules
        if hasattr(test_case, '_in6_filter_rules'):
            self._in6_filter_rules = test_case._in6_filter_rules
        if hasattr(test_case, '_in_nat_rules'):
            self._in_nat_rules = test_case._in_nat_rules
        self._test_case = test_case

    def host_call_plugin(self, _1, _2, plugin, method, args):
        """Mock method four host_call_plugin to be used in unit tests
           for the dom0 iptables Firewall drivers for XenAPI

        """
        if plugin == "xenhost" and method == "iptables_config":
            # The command to execute is a json-encoded list
            cmd_args = args.get('cmd_args', None)
            cmd = json.loads(cmd_args)
            if not cmd:
                ret_str = ''
            else:
                output = ''
                process_input = args.get('process_input', None)
                if cmd == ['ip6tables-save', '-t', 'filter']:
                    output = '\n'.join(self._in6_filter_rules)
                if cmd == ['iptables-save', '-t', 'filter']:
                    output = '\n'.join(self._in_filter_rules)
                if cmd == ['iptables-save', '-t', 'nat']:
                    output = '\n'.join(self._in_nat_rules)
                if cmd == ['iptables-restore', ]:
                    lines = process_input.split('\n')
                    if '*filter' in lines:
                        if self._test_case is not None:
                            self._test_case._out_rules = lines
                        output = '\n'.join(lines)
                if cmd == ['ip6tables-restore', ]:
                    lines = process_input.split('\n')
                    if '*filter' in lines:
                        output = '\n'.join(lines)
                ret_str = fake.as_json(out=output, err='')
        return ret_str


def stub_out_vm_methods(stubs):
    def fake_shutdown(self, inst, vm, method="clean"):
        pass

    def fake_acquire_bootlock(self, vm):
        pass

    def fake_release_bootlock(self, vm):
        pass

    def fake_spawn_rescue(self, context, inst, network_info, image_meta):
        inst._rescue = False

    stubs.Set(vmops.VMOps, "_shutdown", fake_shutdown)
    stubs.Set(vmops.VMOps, "_acquire_bootlock", fake_acquire_bootlock)
    stubs.Set(vmops.VMOps, "_release_bootlock", fake_release_bootlock)
    stubs.Set(vmops.VMOps, "spawn_rescue", fake_spawn_rescue)


class FakeSessionForVolumeTests(fake.SessionBase):
    """ Stubs out a XenAPISession for Volume tests """
    def __init__(self, uri):
        super(FakeSessionForVolumeTests, self).__init__(uri)

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
    """ Stubs out a XenAPISession for Volume tests: it injects failures """
    def __init__(self, uri):
        super(FakeSessionForVolumeFailedTests, self).__init__(uri)

    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        # This is for testing failure
        raise fake.Failure([['INVALID_VDI', 'session', self._session]])

    def PBD_unplug(self, _1, ref):
        rec = fake.get_record('PBD', ref)
        rec['currently-attached'] = False

    def SR_forget(self, _1, ref):
        pass


class FakeSessionForMigrationTests(fake.SessionBase):
    """Stubs out a XenAPISession for Migration tests"""
    def __init__(self, uri):
        super(FakeSessionForMigrationTests, self).__init__(uri)

    def VDI_get_by_uuid(self, *args):
        return 'hurr'

    def VM_start(self, _1, ref, _2, _3):
        vm = fake.get_record('VM', ref)
        if vm['power_state'] != 'Halted':
            raise fake.Failure(['VM_BAD_POWER_STATE', ref, 'Halted',
                                  vm['power_state']])
        vm['power_state'] = 'Running'
        vm['is_a_template'] = False
        vm['is_control_domain'] = False
        vm['domid'] = random.randrange(1, 1 << 16)

    def VM_set_name_label(self, *args):
        pass

    def VDI_set_name_label(self, session_ref, vdi_ref, name_label):
        pass


def stub_out_migration_methods(stubs):
    def fake_create_snapshot(self, instance):
        return 'vm_ref', dict(image='foo', snap='bar')

    @classmethod
    def fake_get_vdi(cls, session, vm_ref):
        vdi_ref = fake.create_vdi(name_label='derp', read_only=False,
                             sr_ref='herp', sharable=False)
        vdi_rec = session.call_xenapi("VDI.get_record", vdi_ref)
        return vdi_ref, {'uuid': vdi_rec['uuid'], }

    def fake_shutdown(self, inst, vm, hard=True):
        pass

    @classmethod
    def fake_sr(cls, session, *args):
        pass

    @classmethod
    def fake_get_sr_path(cls, *args):
        return "fake"

    def fake_destroy(*args, **kwargs):
        pass

    def fake_reset_network(*args, **kwargs):
        pass

    stubs.Set(vmops.VMOps, '_destroy', fake_destroy)
    stubs.Set(vm_utils.VMHelper, 'scan_default_sr', fake_sr)
    stubs.Set(vm_utils.VMHelper, 'scan_sr', fake_sr)
    stubs.Set(vmops.VMOps, '_create_snapshot', fake_create_snapshot)
    stubs.Set(vm_utils.VMHelper, 'get_vdi_for_vm_safely', fake_get_vdi)
    stubs.Set(xenapi_conn.XenAPISession, 'wait_for_task', lambda x, y, z: None)
    stubs.Set(vm_utils.VMHelper, 'get_sr_path', fake_get_sr_path)
    stubs.Set(vmops.VMOps, 'reset_network', fake_reset_network)
    stubs.Set(vmops.VMOps, '_shutdown', fake_shutdown)
