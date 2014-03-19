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
Stubouts for the test suite
"""

import contextlib

import mock

from nova.virt.vmwareapi import driver
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import network_util
from nova.virt.vmwareapi import vmware_images


def fake_get_vim_object(arg):
    """Stubs out the VMwareAPISession's get_vim_object method."""
    return fake.FakeVim()


def fake_is_vim_object(arg, module):
    """Stubs out the VMwareAPISession's is_vim_object method."""
    return isinstance(module, fake.FakeVim)


def fake_temp_method_exception():
    raise error_util.VimFaultException(
            [error_util.NOT_AUTHENTICATED],
            "Session Empty/Not Authenticated")


def fake_temp_session_exception():
    raise error_util.SessionConnectionException("it's a fake!",
            "Session Exception")


def fake_session_file_exception():
    fault_list = [error_util.FILE_ALREADY_EXISTS]
    raise error_util.VimFaultException(fault_list,
                                       Exception('fake'))


def set_stubs(stubs):
    """Set the stubs."""
    stubs.Set(network_util, 'get_network_with_the_name',
              fake.fake_get_network)
    stubs.Set(vmware_images, 'fetch_image', fake.fake_fetch_image)
    stubs.Set(vmware_images, 'get_vmdk_size_and_properties',
              fake.fake_get_vmdk_size_and_properties)
    stubs.Set(vmware_images, 'upload_image', fake.fake_upload_image)
    stubs.Set(driver.VMwareAPISession, "_get_vim_object",
              fake_get_vim_object)
    stubs.Set(driver.VMwareAPISession, "_is_vim_object",
              fake_is_vim_object)


def fake_suds_context(calls={}):
    """Generate a suds client which automatically mocks all SOAP method calls.

    Calls are stored in <calls>, indexed by the name of the call. If you need
    to mock the behaviour of specific API calls you can pre-populate <calls>
    with appropriate Mock objects.
    """

    class fake_factory:
        def create(self, name):
            return mock.NonCallableMagicMock(name=name)

    class fake_service:
        def __getattr__(self, attr_name):
            if attr_name in calls:
                return calls[attr_name]

            mock_call = mock.MagicMock(name=attr_name)
            calls[attr_name] = mock_call
            return mock_call

    class fake_client:
        def __init__(self, wdsl_url, **kwargs):
            self.service = fake_service()
            self.factory = fake_factory()

    return contextlib.nested(
        mock.patch('suds.client.Client', fake_client),

        # As we're not connecting to a real host there's no need to wait
        # between retries
        mock.patch.object(driver, 'TIME_BETWEEN_API_CALL_RETRIES', 0)
    )
