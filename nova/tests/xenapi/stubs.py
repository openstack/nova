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

from nova.virt import xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import volume_utils


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


class FakeSessionForVMTests(fake.SessionBase):
    """ Stubs out a XenAPISession for VM tests """
    def __init__(self, uri):
        super(FakeSessionForVMTests, self).__init__(uri)

    def network_get_all_records_where(self, _1, _2):
        return self.xenapi.network.get_all_records()

    def host_call_plugin(self, _1, _2, _3, _4, _5):
        return ''

    def VM_start(self, _1, ref, _2, _3):
        vm = fake.get_record('VM', ref)
        if vm['power_state'] != 'Halted':
            raise fake.Failure(['VM_BAD_POWER_STATE', ref, 'Halted',
                                  vm['power_state']])
        vm['power_state'] = 'Running'
        vm['is_a_template'] = False
        vm['is_control_domain'] = False


class FakeSessionForVolumeTests(fake.SessionBase):
    """ Stubs out a XenAPISession for Volume tests """
    def __init__(self, uri):
        super(FakeSessionForVolumeTests, self).__init__(uri)

    def VBD_plug(self, _1, ref):
        rec = fake.get_record('VBD', ref)
        rec['currently-attached'] = True

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
