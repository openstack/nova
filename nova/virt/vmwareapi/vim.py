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
Class facilitating SOAP calls to ESX/ESXi server

"""

import httplib

import ZSI

from nova.virt.vmwareapi import VimService_services

RESP_NOT_XML_ERROR = 'Response is "text/html", not "text/xml'
CONN_ABORT_ERROR = 'Software caused connection abort'
ADDRESS_IN_USE_ERROR = 'Address already in use'


class VimException(Exception):
    """The VIM Exception class"""

    def __init__(self, exception_summary, excep):
        """Initializer"""
        Exception.__init__(self)
        self.exception_summary = exception_summary
        self.exception_obj = excep

    def __str__(self):
        """The informal string representation of the object"""
        return self.exception_summary + str(self.exception_obj)


class SessionOverLoadException(VimException):
    """Session Overload Exception"""
    pass


class SessionFaultyException(VimException):
    """Session Faulty Exception"""
    pass


class VimAttributeError(VimException):
    """Attribute Error"""
    pass


class Vim:
    """The VIM Object"""

    def __init__(self,
                 protocol="https",
                 host="localhost",
                 trace=None):
        """
        Initializer

        protocol: http or https
        host    : ESX IPAddress[:port] or ESX Hostname[:port]
        trace   : File handle (eg. sys.stdout, sys.stderr ,
                    open("file.txt",w), Use it only for debugging
                    SOAP Communication
        Creates the necessary Communication interfaces, Gets the
        ServiceContent for initiating SOAP transactions
        """
        self._protocol = protocol
        self._host_name = host
        service_locator = VimService_services.VimServiceLocator()
        connect_string = "%s://%s/sdk" % (self._protocol, self._host_name)
        if trace == None:
            self.proxy = \
                service_locator.getVimPortType(url=connect_string)
        else:
            self.proxy = service_locator.getVimPortType(url=connect_string,
                                                        tracefile=trace)
        self._service_content = \
                self.RetrieveServiceContent("ServiceInstance")

    def get_service_content(self):
        """Gets the service content object"""
        return self._service_content

    def __getattr__(self, attr_name):
        """Makes the API calls and gets the result"""
        try:
            return object.__getattr__(self, attr_name)
        except AttributeError:

            def vim_request_handler(managed_object, **kwargs):
                """
                   managed_object    : Managed Object Reference or Managed
                                       Object Name
                   **kw              : Keyword arguments of the call
                """
                #Dynamic handler for VI SDK Calls
                response = None
                try:
                    request_msg = \
                        self._request_message_builder(attr_name,
                                            managed_object, **kwargs)
                    request = getattr(self.proxy, attr_name)
                    response = request(request_msg)
                    if response == None:
                        return None
                    else:
                        try:
                            return getattr(response, "_returnval")
                        except AttributeError, excep:
                            return None
                except AttributeError, excep:
                    raise VimAttributeError(_("No such SOAP method '%s'"
                         " provided by VI SDK") % (attr_name), excep)
                except ZSI.FaultException, excep:
                    raise SessionFaultyException(_("<ZSI.FaultException> in"
                           " %s:") % (attr_name), excep)
                except ZSI.EvaluateException, excep:
                    raise SessionFaultyException(_("<ZSI.EvaluateException> in"
                           " %s:") % (attr_name), excep)
                except (httplib.CannotSendRequest,
                        httplib.ResponseNotReady,
                        httplib.CannotSendHeader), excep:
                    raise SessionOverLoadException(_("httplib errror in"
                                    " %s: ") % (attr_name), excep)
                except Exception, excep:
                    # Socket errors which need special handling for they
                    # might be caused by ESX API call overload
                    if (str(excep).find(ADDRESS_IN_USE_ERROR) != -1 or
                        str(excep).find(CONN_ABORT_ERROR)):
                        raise SessionOverLoadException(_("Socket error in"
                                    " %s: ") % (attr_name), excep)
                    # Type error that needs special handling for it might be
                    # caused by ESX host API call overload
                    elif str(excep).find(RESP_NOT_XML_ERROR) != -1:
                        raise SessionOverLoadException(_("Type error in "
                                    " %s: ") % (attr_name), excep)
                    else:
                        raise VimException(
                           _("Exception in %s ") % (attr_name), excep)
            return vim_request_handler

    def _request_message_builder(self, method_name, managed_object, **kwargs):
        """Builds the Request Message"""
        #Request Message Builder
        request_msg = getattr(VimService_services, \
                              method_name + "RequestMsg")()
        element = request_msg.new__this(managed_object)
        if type(managed_object) == type(""):
            element.set_attribute_type(managed_object)
        else:
            element.set_attribute_type(managed_object.get_attribute_type())
        request_msg.set_element__this(element)
        for key in kwargs:
            getattr(request_msg, "set_element_" + key)(kwargs[key])
        return request_msg

    def __repr__(self):
        """The official string representation"""
        return "VIM Object"

    def __str__(self):
        """The informal string representation"""
        return "VIM Object"
