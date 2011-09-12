# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Citrix Systems
# All Rights Reserved.
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
#    @author: Tyler Smith, Cisco Systems

import httplib
import json
import socket
import urllib


# FIXME(danwent): All content in this file should be removed once the
# packaging work for the quantum client libraries is complete.
# At that point, we will be able to just install the libraries as a
# dependency and import from quantum.client.* and quantum.common.*
# Until then, we have simplified versions of these classes in this file.

class JSONSerializer(object):
    """This is a simple json-only serializer to use until we can just grab
    the standard serializer from the quantum library.
    """
    def serialize(self, data, content_type):
        try:
            return json.dumps(data)
        except TypeError:
            pass
        return json.dumps(to_primitive(data))

    def deserialize(self, data, content_type):
        return json.loads(data)


# The full client lib will expose more
# granular exceptions, for now, just try to distinguish
# between the cases we care about.
class QuantumNotFoundException(Exception):
    """Indicates that Quantum Server returned 404"""
    pass


class QuantumServerException(Exception):
    """Indicates any non-404 error from Quantum Server"""
    pass


class QuantumIOException(Exception):
    """Indicates network IO trouble reaching Quantum Server"""
    pass


class api_call(object):
    """A Decorator to add support for format and tenant overriding"""
    def __init__(self, func):
        self.func = func

    def __get__(self, instance, owner):
        def with_params(*args, **kwargs):
            """Temporarily set format and tenant for this request"""
            (format, tenant) = (instance.format, instance.tenant)

            if 'format' in kwargs:
                instance.format = kwargs['format']
            if 'tenant' in kwargs:
                instance.tenant = kwargs['tenant']

            ret = None
            try:
                ret = self.func(instance, *args)
            finally:
                (instance.format, instance.tenant) = (format, tenant)
            return ret
        return with_params


class Client(object):
    """A base client class - derived from Glance.BaseClient"""

    action_prefix = '/v1.0/tenants/{tenant_id}'

    """Action query strings"""
    networks_path = "/networks"
    network_path = "/networks/%s"
    ports_path = "/networks/%s/ports"
    port_path = "/networks/%s/ports/%s"
    attachment_path = "/networks/%s/ports/%s/attachment"

    def __init__(self, host="127.0.0.1", port=9696, use_ssl=False, tenant=None,
                 format="xml", testing_stub=None, key_file=None,
                 cert_file=None, logger=None):
        """Creates a new client to some service.

        :param host: The host where service resides
        :param port: The port where service resides
        :param use_ssl: True to use SSL, False to use HTTP
        :param tenant: The tenant ID to make requests with
        :param format: The format to query the server with
        :param testing_stub: A class that stubs basic server methods for tests
        :param key_file: The SSL key file to use if use_ssl is true
        :param cert_file: The SSL cert file to use if use_ssl is true
        """
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.tenant = tenant
        self.format = format
        self.connection = None
        self.testing_stub = testing_stub
        self.key_file = key_file
        self.cert_file = cert_file
        self.logger = logger

    def get_connection_type(self):
        """Returns the proper connection type"""
        if self.testing_stub:
            return self.testing_stub
        elif self.use_ssl:
            return httplib.HTTPSConnection
        else:
            return httplib.HTTPConnection

    def do_request(self, method, action, body=None,
                   headers=None, params=None):
        """Connects to the server and issues a request.
        Returns the result data, or raises an appropriate exception if
        HTTP status code is not 2xx

        :param method: HTTP method ("GET", "POST", "PUT", etc...)
        :param body: string of data to send, or None (default)
        :param headers: mapping of key/value pairs to add as headers
        :param params: dictionary of key/value pairs to add to append
                             to action
        """

        # Ensure we have a tenant id
        if not self.tenant:
            raise Exception(_("Tenant ID not set"))

        # Add format and tenant_id
        action += ".%s" % self.format
        action = Client.action_prefix + action
        action = action.replace('{tenant_id}', self.tenant)

        if type(params) is dict:
            action += '?' + urllib.urlencode(params)

        try:
            connection_type = self.get_connection_type()
            headers = headers or {"Content-Type":
                                      "application/%s" % self.format}

            # Open connection and send request, handling SSL certs
            certs = {'key_file': self.key_file, 'cert_file': self.cert_file}
            certs = dict((x, certs[x]) for x in certs if certs[x] != None)

            if self.use_ssl and len(certs):
                c = connection_type(self.host, self.port, **certs)
            else:
                c = connection_type(self.host, self.port)

            if self.logger:
                self.logger.debug(
                    _("Quantum Client Request:\n%(method)s %(action)s\n" %
                                    locals()))
                if body:
                    self.logger.debug(body)

            c.request(method, action, body, headers)
            res = c.getresponse()
            status_code = self.get_status_code(res)
            data = res.read()

            if self.logger:
                self.logger.debug("Quantum Client Reply (code = %s) :\n %s" \
                        % (str(status_code), data))

            if status_code == httplib.NOT_FOUND:
                raise QuantumNotFoundException(
                    _("Quantum entity not found: %s" % data))

            if status_code in (httplib.OK,
                               httplib.CREATED,
                               httplib.ACCEPTED,
                               httplib.NO_CONTENT):
                if data is not None and len(data):
                    return self.deserialize(data, status_code)
            else:
                raise QuantumServerException(
                      _("Server %(status_code)s error: %(data)s"
                                        % locals()))

        except (socket.error, IOError), e:
            raise QuantumIOException(_("Unable to connect to "
                              "server. Got error: %s" % e))

    def get_status_code(self, response):
        """Returns the integer status code from the response, which
        can be either a Webob.Response (used in testing) or httplib.Response
        """
        if hasattr(response, 'status_int'):
            return response.status_int
        else:
            return response.status

    def serialize(self, data):
        if not data:
            return None
        elif type(data) is dict:
            return JSONSerializer().serialize(data, self.content_type())
        else:
            raise Exception(_("unable to deserialize object of type = '%s'" %
                              type(data)))

    def deserialize(self, data, status_code):
        if status_code == 202:
            return data
        return JSONSerializer().deserialize(data, self.content_type())

    def content_type(self, format=None):
        if not format:
            format = self.format
        return "application/%s" % (format)

    @api_call
    def list_networks(self):
        """Fetches a list of all networks for a tenant"""
        return self.do_request("GET", self.networks_path)

    @api_call
    def show_network_details(self, network):
        """Fetches the details of a certain network"""
        return self.do_request("GET", self.network_path % (network))

    @api_call
    def create_network(self, body=None):
        """Creates a new network"""
        body = self.serialize(body)
        return self.do_request("POST", self.networks_path, body=body)

    @api_call
    def update_network(self, network, body=None):
        """Updates a network"""
        body = self.serialize(body)
        return self.do_request("PUT", self.network_path % (network), body=body)

    @api_call
    def delete_network(self, network):
        """Deletes the specified network"""
        return self.do_request("DELETE", self.network_path % (network))

    @api_call
    def list_ports(self, network):
        """Fetches a list of ports on a given network"""
        return self.do_request("GET", self.ports_path % (network))

    @api_call
    def show_port_details(self, network, port):
        """Fetches the details of a certain port"""
        return self.do_request("GET", self.port_path % (network, port))

    @api_call
    def create_port(self, network, body=None):
        """Creates a new port on a given network"""
        body = self.serialize(body)
        return self.do_request("POST", self.ports_path % (network), body=body)

    @api_call
    def delete_port(self, network, port):
        """Deletes the specified port from a network"""
        return self.do_request("DELETE", self.port_path % (network, port))

    @api_call
    def set_port_state(self, network, port, body=None):
        """Sets the state of the specified port"""
        body = self.serialize(body)
        return self.do_request("PUT",
            self.port_path % (network, port), body=body)

    @api_call
    def show_port_attachment(self, network, port):
        """Fetches the attachment-id associated with the specified port"""
        return self.do_request("GET", self.attachment_path % (network, port))

    @api_call
    def attach_resource(self, network, port, body=None):
        """Sets the attachment-id of the specified port"""
        body = self.serialize(body)
        return self.do_request("PUT",
            self.attachment_path % (network, port), body=body)

    @api_call
    def detach_resource(self, network, port):
        """Removes the attachment-id of the specified port"""
        return self.do_request("DELETE",
                               self.attachment_path % (network, port))
