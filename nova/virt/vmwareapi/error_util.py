# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
Exception classes and SOAP response error checking module
"""

FAULT_NOT_AUTHENTICATED = "NotAuthenticated"
FAULT_ALREADY_EXISTS = "AlreadyExists"


class VimException(Exception):
    """The VIM Exception class"""

    def __init__(self, exception_summary, excep):
        Exception.__init__(self)
        self.exception_summary = exception_summary
        self.exception_obj = excep

    def __str__(self):
        return self.exception_summary + str(self.exception_obj)


class SessionOverLoadException(VimException):
    """Session Overload Exception"""
    pass


class VimAttributeError(VimException):
    """VI Attribute Error"""
    pass


class VimFaultException(Exception):
    """The VIM Fault exception class"""

    def __init__(self, fault_list, excep):
        Exception.__init__(self)
        self.fault_list = fault_list
        self.exception_obj = excep

    def __str__(self):
        return str(self.exception_obj)


class FaultCheckers:
    """Methods for fault checking of SOAP response. Per Method error handlers
    for which we desire error checking are defined. SOAP faults are
    embedded in the SOAP as a property and not as a SOAP fault."""

    @classmethod
    def retrieveproperties_fault_checker(self, resp_obj):
        """Checks the RetrieveProperties response for errors. Certain faults
        are sent as a part of the SOAP body as property of missingSet.
        For example NotAuthenticated fault"""
        fault_list = []
        for obj_cont in resp_obj:
            if hasattr(obj_cont, "missingSet"):
                for missing_elem in obj_cont.missingSet:
                    fault_type = missing_elem.fault.fault.__class__.__name__
                    #Fault needs to be added to the type of fault for
                    #uniformity in error checking as SOAP faults define
                    fault_list.append(fault_type)
        if fault_list:
            exc_msg_list = ', '.join(fault_list)
            raise VimFaultException(fault_list, Exception(_("Error(s) %s "
                    "occurred in the call to RetrieveProperties") %
                    exc_msg_list))
