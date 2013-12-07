# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
Exception classes and SOAP response error checking module.
"""
from nova import exception

from nova.openstack.common.gettextutils import _


FAULT_NOT_AUTHENTICATED = "NotAuthenticated"
FAULT_ALREADY_EXISTS = "AlreadyExists"


class VimException(Exception):
    """The VIM Exception class."""

    def __init__(self, exception_summary, excep):
        Exception.__init__(self)
        self.exception_summary = exception_summary
        self.exception_obj = excep

    def __str__(self):
        return self.exception_summary + str(self.exception_obj)


class SessionOverLoadException(VimException):
    """Session Overload Exception."""
    pass


class VimAttributeError(VimException):
    """VI Attribute Error."""
    pass


class VimFaultException(Exception):
    """The VIM Fault exception class."""

    def __init__(self, fault_list, excep):
        Exception.__init__(self)
        self.fault_list = fault_list
        self.exception_obj = excep

    def __str__(self):
        return str(self.exception_obj)


class FaultCheckers(object):
    """
    Methods for fault checking of SOAP response. Per Method error handlers
    for which we desire error checking are defined. SOAP faults are
    embedded in the SOAP messages as properties and not as SOAP faults.
    """

    @staticmethod
    def retrievepropertiesex_fault_checker(resp_obj):
        """
        Checks the RetrievePropertiesEx response for errors. Certain faults
        are sent as part of the SOAP body as property of missingSet.
        For example NotAuthenticated fault.
        """
        fault_list = []
        if not resp_obj:
            # This is the case when the session has timed out. ESX SOAP server
            # sends an empty RetrievePropertiesResponse. Normally missingSet in
            # the returnval field has the specifics about the error, but that's
            # not the case with a timed out idle session. It is as bad as a
            # terminated session for we cannot use the session. So setting
            # fault to NotAuthenticated fault.
            fault_list = ["NotAuthenticated"]
        else:
            for obj_cont in resp_obj.objects:
                if hasattr(obj_cont, "missingSet"):
                    for missing_elem in obj_cont.missingSet:
                        fault_type = missing_elem.fault.fault.__class__
                        # Fault needs to be added to the type of fault for
                        # uniformity in error checking as SOAP faults define
                        fault_list.append(fault_type.__name__)
        if fault_list:
            exc_msg_list = ', '.join(fault_list)
            raise VimFaultException(fault_list, Exception(_("Error(s) %s "
                    "occurred in the call to RetrievePropertiesEx") %
                    exc_msg_list))


class VMwareDriverException(exception.NovaException):
    """Base class for all exceptions raised by the VMware Driver.

    All exceptions raised by the VMwareAPI drivers should raise
    an exception descended from this class as a root. This will
    allow the driver to potentially trap problems related to its
    own internal configuration before halting the nova-compute
    node.
    """
    msg_fmt = _("VMware Driver fault.")


class VMwareDriverConfigurationException(VMwareDriverException):
    """Base class for all configuration exceptions.
    """
    msg_fmt = _("VMware Driver configuration fault.")


class UseLinkedCloneConfigurationFault(VMwareDriverConfigurationException):
    msg_fmt = _("No default value for use_linked_clone found.")
