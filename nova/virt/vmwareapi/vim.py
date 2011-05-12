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
Classes for making VMware VI SOAP calls.
"""

import httplib

try:
    import suds
except ImportError:
    suds = None

from nova import flags
from nova.virt.vmwareapi import error_util

RESP_NOT_XML_ERROR = 'Response is "text/html", not "text/xml"'
CONN_ABORT_ERROR = 'Software caused connection abort'
ADDRESS_IN_USE_ERROR = 'Address already in use'

FLAGS = flags.FLAGS
flags.DEFINE_string('vmwareapi_wsdl_loc',
                   None,
                   'VIM Service WSDL Location'
                   'e.g http://<server>/vimService.wsdl'
                   'Due to a bug in vSphere ESX 4.1 default wsdl'
                   'Refer readme-vmware to setup')


if suds:

    class VIMMessagePlugin(suds.plugin.MessagePlugin):

        def addAttributeForValue(self, node):
            # suds does not handle AnyType properly.
            # VI SDK requires type attribute to be set when AnyType is used
            if node.name == 'value':
                node.set('xsi:type', 'xsd:string')

        def marshalled(self, context):
            """suds will send the specified soap envelope.
            Provides the plugin with the opportunity to prune empty
            nodes and fixup nodes before sending it to the server.
            """
            # suds builds the entire request object based on the wsdl schema.
            # VI SDK throws server errors if optional SOAP nodes are sent
            # without values, e.g. <test/> as opposed to <test>test</test>
            context.envelope.prune()
            context.envelope.walk(self.addAttributeForValue)


class Vim:
    """The VIM Object."""

    def __init__(self,
                 protocol="https",
                 host="localhost"):
        """
        Creates the necessary Communication interfaces and gets the
        ServiceContent for initiating SOAP transactions.

        protocol: http or https
        host    : ESX IPAddress[:port] or ESX Hostname[:port]
        """
        if not suds:
            raise Exception(_("Unable to import suds."))

        self._protocol = protocol
        self._host_name = host
        wsdl_url = FLAGS.vmwareapi_wsdl_loc
        if wsdl_url is None:
            raise Exception(_("Must specify vmwareapi_wsdl_loc"))
        # TODO(sateesh): Use this when VMware fixes their faulty wsdl
        #wsdl_url = '%s://%s/sdk/vimService.wsdl' % (self._protocol,
        #        self._host_name)
        url = '%s://%s/sdk' % (self._protocol, self._host_name)
        self.client = suds.client.Client(wsdl_url, location=url,
                            plugins=[VIMMessagePlugin()])
        self._service_content = \
                self.RetrieveServiceContent("ServiceInstance")

    def get_service_content(self):
        """Gets the service content object."""
        return self._service_content

    def __getattr__(self, attr_name):
        """Makes the API calls and gets the result."""
        try:
            return object.__getattr__(self, attr_name)
        except AttributeError:

            def vim_request_handler(managed_object, **kwargs):
                """
                Builds the SOAP message and parses the response for fault
                checking and other errors.

                managed_object    : Managed Object Reference or Managed
                                    Object Name
                **kwargs          : Keyword arguments of the call
                """
                # Dynamic handler for VI SDK Calls
                try:
                    request_mo = \
                        self._request_managed_object_builder(managed_object)
                    request = getattr(self.client.service, attr_name)
                    response = request(request_mo, **kwargs)
                    # To check for the faults that are part of the message body
                    # and not returned as Fault object response from the ESX
                    # SOAP server
                    if hasattr(error_util.FaultCheckers,
                                    attr_name.lower() + "_fault_checker"):
                        fault_checker = getattr(error_util.FaultCheckers,
                                    attr_name.lower() + "_fault_checker")
                        fault_checker(response)
                    return response
                # Catch the VimFaultException that is raised by the fault
                # check of the SOAP response
                except error_util.VimFaultException, excep:
                    raise
                except suds.WebFault, excep:
                    doc = excep.document
                    detail = doc.childAtPath("/Envelope/Body/Fault/detail")
                    fault_list = []
                    for child in detail.getChildren():
                        fault_list.append(child.get("type"))
                    raise error_util.VimFaultException(fault_list, excep)
                except AttributeError, excep:
                    raise error_util.VimAttributeError(_("No such SOAP method "
                         "'%s' provided by VI SDK") % (attr_name), excep)
                except (httplib.CannotSendRequest,
                        httplib.ResponseNotReady,
                        httplib.CannotSendHeader), excep:
                    raise error_util.SessionOverLoadException(_("httplib "
                                    "error in %s: ") % (attr_name), excep)
                except Exception, excep:
                    # Socket errors which need special handling for they
                    # might be caused by ESX API call overload
                    if (str(excep).find(ADDRESS_IN_USE_ERROR) != -1 or
                        str(excep).find(CONN_ABORT_ERROR)) != -1:
                        raise error_util.SessionOverLoadException(_("Socket "
                                    "error in %s: ") % (attr_name), excep)
                    # Type error that needs special handling for it might be
                    # caused by ESX host API call overload
                    elif str(excep).find(RESP_NOT_XML_ERROR) != -1:
                        raise error_util.SessionOverLoadException(_("Type "
                                    "error in  %s: ") % (attr_name), excep)
                    else:
                        raise error_util.VimException(
                           _("Exception in %s ") % (attr_name), excep)
            return vim_request_handler

    def _request_managed_object_builder(self, managed_object):
        """Builds the request managed object."""
        # Request Managed Object Builder
        if type(managed_object) == type(""):
            mo = suds.sudsobject.Property(managed_object)
            mo._type = managed_object
        else:
            mo = managed_object
        return mo

    def __repr__(self):
        return "VIM Object"

    def __str__(self):
        return "VIM Object"
