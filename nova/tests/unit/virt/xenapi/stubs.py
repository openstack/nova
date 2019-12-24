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
import mock
from os_xenapi.client import session
from os_xenapi.client import XenAPI

from nova import test
from nova.virt.xenapi import fake


def stubout_session(test, cls, product_version=(5, 6, 2),
                    product_brand='XenServer', platform_version=(1, 9, 0),
                    **opt_args):
    """Stubs out methods from XenAPISession."""
    test.stub_out('os_xenapi.client.session.XenAPISession._create_session',
                  lambda s, url: cls(url, **opt_args))
    test.stub_out('os_xenapi.client.session.XenAPISession.'
                  '_get_product_version_and_brand',
                  lambda s: (product_version, product_brand))
    test.stub_out('os_xenapi.client.session.XenAPISession.'
                  '_get_platform_version',
                  lambda s: platform_version)


def _make_fake_vdi():
    sr_ref = fake.get_all('SR')[0]
    vdi_ref = fake.create_vdi('', sr_ref)
    vdi_rec = fake.get_record('VDI', vdi_ref)
    return vdi_rec['uuid']


class FakeSessionForVMTests(fake.SessionBase):
    """Stubs out a XenAPISession for VM tests."""

    def host_call_plugin(self, _1, _2, plugin, method, _5):
        plugin = plugin.rstrip('.py')

        if plugin == 'glance' and method == 'download_vhd2':
            root_uuid = _make_fake_vdi()
            return pickle.dumps(dict(root=dict(uuid=root_uuid)))
        else:
            return (super(FakeSessionForVMTests, self).
                    host_call_plugin(_1, _2, plugin, method, _5))

    def VM_start(self, _1, ref, _2, _3):
        vm = fake.get_record('VM', ref)
        if vm['power_state'] != 'Halted':
            raise XenAPI.Failure(['VM_BAD_POWER_STATE', ref, 'Halted',
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
            raise XenAPI.Failure([['INVALID_VDI', 'session', self._session]])


class FakeSessionForVolumeFailedTests(FakeSessionForVolumeTests):
    """Stubs out a XenAPISession for Volume tests: it injects failures."""
    def VDI_introduce(self, _1, uuid, _2, _3, _4, _5,
                      _6, _7, _8, _9, _10, _11):
        # This is for testing failure
        raise XenAPI.Failure([['INVALID_VDI', 'session', self._session]])

    def PBD_unplug(self, _1, ref):
        rec = fake.get_record('PBD', ref)
        rec['currently-attached'] = False

    def SR_forget(self, _1, ref):
        pass


class FakeSessionForFailedMigrateTests(FakeSessionForVMTests):
    def VM_assert_can_migrate(self, session, vmref, migrate_data,
                              live, vdi_map, vif_map, options):
        raise XenAPI.Failure("XenAPI VM.assert_can_migrate failed")

    def host_migrate_receive(self, session, hostref, networkref, options):
        raise XenAPI.Failure("XenAPI host.migrate_receive failed")

    def VM_migrate_send(self, session, vmref, migrate_data, islive, vdi_map,
                        vif_map, options):
        raise XenAPI.Failure("XenAPI VM.migrate_send failed")


# FIXME(sirp): XenAPITestBase is deprecated, all tests should be converted
# over to use XenAPITestBaseNoDB
class XenAPITestBase(test.TestCase):
    def setUp(self):
        super(XenAPITestBase, self).setUp()
        self.useFixture(ReplaceModule('XenAPI', fake))
        fake.reset()

    def stubout_get_this_vm_uuid(self):
        def f(session):
            vms = [rec['uuid'] for rec
                   in fake.get_all_records('VM').values()
                   if rec['is_control_domain']]
            return vms[0]
        self.stub_out('nova.virt.xenapi.vm_utils.get_this_vm_uuid', f)


class XenAPITestBaseNoDB(test.NoDBTestCase):
    def setUp(self):
        super(XenAPITestBaseNoDB, self).setUp()
        self.useFixture(ReplaceModule('XenAPI', fake))
        fake.reset()

    @staticmethod
    def get_fake_session(error=None):
        fake_session = mock.MagicMock()
        session.apply_session_helpers(fake_session)

        if error is not None:
            class FakeException(Exception):
                details = [error, "a", "b", "c"]

            fake_session.XenAPI.Failure = FakeException
            fake_session.call_xenapi.side_effect = FakeException

        return fake_session
