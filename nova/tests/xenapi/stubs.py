# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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

"""Stubouts, mocks and fixtures for the test suite"""

import eventlet
import json
import random

from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import vmops
from nova import utils


def stubout_instance_snapshot(stubs):
    @classmethod
    def fake_fetch_image(cls, context, session, instance, image, user,
                         project, type):
        from nova.virt.xenapi.fake import create_vdi
        name_label = "instance-%s" % instance.id
        #TODO: create fake SR record
        sr_ref = "fakesr"
        vdi_ref = create_vdi(name_label=name_label, read_only=False,
                             sr_ref=sr_ref, sharable=False)
        vdi_rec = session.get_xenapi().VDI.get_record(vdi_ref)
        vdi_uuid = vdi_rec['uuid']
        return [dict(vdi_type='os', vdi_uuid=vdi_uuid)]

    stubs.Set(vm_utils.VMHelper, 'fetch_image', fake_fetch_image)

    def fake_parse_xmlrpc_value(val):
        return val

    stubs.Set(xenapi_conn, '_parse_xmlrpc_value', fake_parse_xmlrpc_value)

    def fake_wait_for_vhd_coalesce(session, instance_id, sr_ref, vdi_ref,
                              original_parent_uuid):
        #TODO(sirp): Should we actually fake out the data here
        return "fakeparent"

    stubs.Set(vm_utils, 'wait_for_vhd_coalesce', fake_wait_for_vhd_coalesce)


def stubout_session(stubs, cls):
    """Stubs out two methods from XenAPISession"""
    def fake_import(self):
        """Stubs out get_imported_xenapi of XenAPISession"""
        fake_module = 'nova.virt.xenapi.fake'
        from_list = ['fake']
        return __import__(fake_module, globals(), locals(), from_list, -1)

    stubs.Set(xenapi_conn.XenAPISession, '_create_session',
                       lambda s, url: cls(url))
    stubs.Set(xenapi_conn.XenAPISession, 'get_imported_xenapi',
                       fake_import)


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
    """Assumes VMs never have PV kernels"""

    @classmethod
    def f(cls, *args):
        return False
    stubs.Set(vm_utils.VMHelper, '_determine_is_pv_objectstore', f)


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


def stubout_loopingcall_delay(stubs):
    def fake_start(self, interval, now=True):
        self._running = True
        eventlet.sleep(1)
        self.f(*self.args, **self.kw)
        # This would fail before parallel xenapi calls were fixed
        assert self._running == False
    stubs.Set(utils.LoopingCall, 'start', fake_start)


class FakeSessionForVMTests(fake.SessionBase):
    """ Stubs out a XenAPISession for VM tests """
    def __init__(self, uri):
        super(FakeSessionForVMTests, self).__init__(uri)

    def host_call_plugin(self, _1, _2, plugin, method, _5):
        # If the call is for 'copy_kernel_vdi' return None.
        if method == 'copy_kernel_vdi':
            return
        sr_ref = fake.get_all('SR')[0]
        vdi_ref = fake.create_vdi('', False, sr_ref, False)
        vdi_rec = fake.get_record('VDI', vdi_ref)
        if plugin == "glance" and method == "download_vhd":
            ret_str = json.dumps([dict(vdi_type='os',
                    vdi_uuid=vdi_rec['uuid'])])
        else:
            ret_str = vdi_rec['uuid']
        return '<string>%s</string>' % ret_str

    def host_call_plugin_swap(self, _1, _2, plugin, method, _5):
        sr_ref = fake.get_all('SR')[0]
        vdi_ref = fake.create_vdi('', False, sr_ref, False)
        vdi_rec = fake.get_record('VDI', vdi_ref)
        if plugin == "glance" and method == "download_vhd":
            swap_vdi_ref = fake.create_vdi('', False, sr_ref, False)
            swap_vdi_rec = fake.get_record('VDI', swap_vdi_ref)
            ret_str = json.dumps(
                    [dict(vdi_type='os', vdi_uuid=vdi_rec['uuid']),
                    dict(vdi_type='swap', vdi_uuid=swap_vdi_rec['uuid'])])
        else:
            ret_str = vdi_rec['uuid']
        return '<string>%s</string>' % ret_str

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


def stub_out_vm_methods(stubs):
    def fake_shutdown(self, inst, vm, method="clean"):
        pass

    def fake_acquire_bootlock(self, vm):
        pass

    def fake_release_bootlock(self, vm):
        pass

    def fake_spawn_rescue(self, context, inst, network_info):
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


def stub_out_migration_methods(stubs):
    def fake_get_snapshot(self, instance):
        return 'vm_ref', dict(image='foo', snap='bar')

    @classmethod
    def fake_get_vdi(cls, session, vm_ref):
        vdi_ref = fake.create_vdi(name_label='derp', read_only=False,
                             sr_ref='herp', sharable=False)
        vdi_rec = session.get_xenapi().VDI.get_record(vdi_ref)
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
    stubs.Set(vmops.VMOps, '_get_snapshot', fake_get_snapshot)
    stubs.Set(vm_utils.VMHelper, 'get_vdi_for_vm_safely', fake_get_vdi)
    stubs.Set(xenapi_conn.XenAPISession, 'wait_for_task', lambda x, y, z: None)
    stubs.Set(vm_utils.VMHelper, 'get_sr_path', fake_get_sr_path)
    stubs.Set(vmops.VMOps, 'reset_network', fake_reset_network)
    stubs.Set(vmops.VMOps, '_shutdown', fake_shutdown)
