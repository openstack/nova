# Copyright (c) 2022 SAP SE
# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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


"""
Test suite for VMwareAPI Session
"""

from unittest import mock

from oslo_vmware import exceptions as vexec

from nova import test
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi import session


def _fake_create_session(inst):
    _session = vmwareapi_fake.DataObject()
    _session.key = 'fake_key'
    _session.userName = 'fake_username'
    _session._pbm_wsdl_loc = None
    _session._pbm = None
    inst._session = _session


def _fake_fetch_moref_impl(inst, _):
    inst.moref = vmwareapi_fake.ManagedObjectReference(
        value=mock.sentinel.moref2)


class FakeStableMoRefProxy(session.StableMoRefProxy):
    def __init__(self, ref=None):
        super(FakeStableMoRefProxy, self).__init__(
            ref or vmwareapi_fake.ManagedObjectReference(
                value=mock.sentinel.moref))

    def fetch_moref(self, session):
        pass

    def __repr__(self):
        return "FakeStableMoRefProxy({!r})".format(self.moref)


class StableMoRefProxyTestCase(test.NoDBTestCase):
    def test_proxy(self):
        ref = FakeStableMoRefProxy()
        self.assertEqual(mock.sentinel.moref, ref.value)
        self.assertEqual("ManagedObject", ref._type)

    def test_proxy_classes(self):
        # Necessary for suds serialisation
        ref = FakeStableMoRefProxy()
        self.assertEqual("ManagedObjectReference", ref.__class__.__name__)


class VMwareSessionTestCase(test.NoDBTestCase):

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=False)
    def test_call_method(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession,
                              '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession,
                              'invoke_api'),
        ) as (fake_create, fake_invoke):
            _session = session.VMwareAPISession()
            _session._vim = mock.Mock()
            module = mock.Mock()
            _session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira', _session._vim)

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_vim(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession,
                              '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession,
                              'invoke_api'),
        ) as (fake_create, fake_invoke):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            _session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira')

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_no_recovery(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession, 'invoke_api'),
            mock.patch.object(FakeStableMoRefProxy, 'fetch_moref'),
        ) as (fake_create, fake_invoke, fake_fetch_moref):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            ref = FakeStableMoRefProxy()

            _session._call_method(
                module, mock.sentinel.method_arg, ref, ref=ref)

            fake_invoke.assert_called_once_with(
                module, mock.sentinel.method_arg, ref, ref=ref)
            fake_fetch_moref.assert_not_called()

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_recovery_arg_failed(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession, 'invoke_api'),
            mock.patch.object(FakeStableMoRefProxy, 'fetch_moref'),
        ) as (fake_create, fake_invoke, fake_fetch_moref):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            ref = FakeStableMoRefProxy()
            fake_invoke.side_effect = [vexec.ManagedObjectNotFoundException]

            self.assertRaises(vexec.ManagedObjectNotFoundException,
                _session._call_method, module, mock.sentinel.method_arg, ref)

            fake_invoke.assert_called_once_with(
                module, mock.sentinel.method_arg, ref)
            fake_fetch_moref.assert_not_called()

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_recovery_kwarg_failed(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession, 'invoke_api'),
            mock.patch.object(FakeStableMoRefProxy, 'fetch_moref'),
        ) as (fake_create, fake_invoke, fake_fetch_moref):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            ref = FakeStableMoRefProxy()
            fake_invoke.side_effect = [vexec.ManagedObjectNotFoundException]

            self.assertRaises(vexec.ManagedObjectNotFoundException,
                              _session._call_method, module,
                              mock.sentinel.method_arg, ref=ref)

            fake_invoke.assert_called_once_with(
                module, mock.sentinel.method_arg, ref=ref)
            fake_fetch_moref.assert_not_called()

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_recovery_arg_success(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession, 'invoke_api'),
            mock.patch.object(FakeStableMoRefProxy,
                              'fetch_moref', _fake_fetch_moref_impl),
        ) as (fake_create, fake_invoke, fake_fetch_moref):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            ref = FakeStableMoRefProxy()

            fake_invoke.side_effect = [vexec.ManagedObjectNotFoundException(
                details=dict(obj=mock.sentinel.moref),
            ), None]
            _session._call_method(module, mock.sentinel.method_arg, ref)
            fake_invoke.assert_called_with(
                module, mock.sentinel.method_arg, ref)

    @mock.patch.object(session.VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_recovery_kwarg_success(self, mock_is_vim):
        with test.nested(
            mock.patch.object(session.VMwareAPISession, '_create_session',
                              _fake_create_session),
            mock.patch.object(session.VMwareAPISession, 'invoke_api'),
            mock.patch.object(FakeStableMoRefProxy,
                                  'fetch_moref', _fake_fetch_moref_impl),
        ) as (fake_create, fake_invoke, fake_fetch_moref):
            _session = session.VMwareAPISession()
            module = mock.Mock()
            ref = FakeStableMoRefProxy()

            fake_invoke.side_effect = [vexec.ManagedObjectNotFoundException(
                details=dict(obj=mock.sentinel.moref),
            ), None]
            _session._call_method(module, mock.sentinel.method_arg, ref=ref)
            fake_invoke.assert_called_with(
                module, mock.sentinel.method_arg, ref=ref)
