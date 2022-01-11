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

import mock
from nova import test
from nova.tests.unit.virt.vmwareapi import fake as vmwareapi_fake
from nova.virt.vmwareapi.session import VMwareAPISession


def _fake_create_session(inst):
    session = vmwareapi_fake.DataObject()
    session.key = 'fake_key'
    session.userName = 'fake_username'
    session._pbm_wsdl_loc = None
    session._pbm = None
    inst._session = session


class VMwareSessionTestCase(test.NoDBTestCase):

    @mock.patch.object(VMwareAPISession, '_is_vim_object',
                       return_value=False)
    def test_call_method(self, mock_is_vim):
        with test.nested(
                mock.patch.object(VMwareAPISession, '_create_session',
                                  _fake_create_session),
                mock.patch.object(VMwareAPISession, 'invoke_api'),
        ) as (fake_create, fake_invoke):
            session = VMwareAPISession()
            session._vim = mock.Mock()
            module = mock.Mock()
            session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira', session._vim)

    @mock.patch.object(VMwareAPISession, '_is_vim_object',
                       return_value=True)
    def test_call_method_vim(self, mock_is_vim):
        with test.nested(
                mock.patch.object(VMwareAPISession, '_create_session',
                                  _fake_create_session),
                mock.patch.object(VMwareAPISession, 'invoke_api'),
        ) as (fake_create, fake_invoke):
            session = VMwareAPISession()
            module = mock.Mock()
            session._call_method(module, 'fira')
            fake_invoke.assert_called_once_with(module, 'fira')
