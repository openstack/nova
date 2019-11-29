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

from oslo_vmware import exceptions as vexc

import nova.conf
from nova.tests.unit.virt.vmwareapi import fake

CONF = nova.conf.CONF


def fake_get_vim_object(arg):
    """Stubs out the VMwareAPISession's get_vim_object method."""
    return fake.FakeVim()


@property
def fake_vim_prop(arg):
    """Stubs out the VMwareAPISession's vim property access method."""
    return fake.get_fake_vim_object(arg)


def fake_is_vim_object(arg, module):
    """Stubs out the VMwareAPISession's is_vim_object method."""
    return isinstance(module, fake.FakeVim)


def fake_temp_method_exception():
    raise vexc.VimFaultException(
            [vexc.NOT_AUTHENTICATED],
            "Session Empty/Not Authenticated")


def fake_temp_session_exception():
    raise vexc.VimConnectionException("it's a fake!",
            "Session Exception")


def fake_session_file_exception():
    fault_list = [vexc.FILE_ALREADY_EXISTS]
    raise vexc.VimFaultException(fault_list,
                                 Exception('fake'))


def fake_session_permission_exception():
    fault_list = [vexc.NO_PERMISSION]
    fault_string = 'Permission to perform this operation was denied.'
    details = {'privilegeId': 'Resource.AssignVMToPool', 'object': 'domain-c7'}
    raise vexc.VimFaultException(fault_list, fault_string, details=details)


def set_stubs(test):
    """Set the stubs."""

    test.stub_out('nova.virt.vmwareapi.network_util.get_network_with_the_name',
                  fake.fake_get_network)
    test.stub_out('nova.virt.vmwareapi.images.upload_image_stream_optimized',
                  fake.fake_upload_image)
    test.stub_out('nova.virt.vmwareapi.images.fetch_image',
                  fake.fake_fetch_image)
    test.stub_out('nova.virt.vmwareapi.driver.VMwareAPISession.vim',
                  fake_vim_prop)
    test.stub_out('nova.virt.vmwareapi.driver.VMwareAPISession._is_vim_object',
                  fake_is_vim_object)
    test.stub_out('nova.network.neutron.API.update_instance_vnic_index',
                  lambda *args, **kwargs: None)
