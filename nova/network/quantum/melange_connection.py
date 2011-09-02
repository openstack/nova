# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import httplib
import socket
import urllib
import json

from nova import flags


FLAGS = flags.FLAGS

flags.DEFINE_string('melange_host',
                    '127.0.0.1',
                    'HOST for connecting to melange')

flags.DEFINE_string('melange_port',
                    '9898',
                    'PORT for connecting to melange')

json_content_type = {'Content-type': "application/json"}


# FIXME(danwent): talk to the Melange folks about creating a
# client lib that we can import as a library, instead of
# have to have all of the client code in here.
class MelangeConnection(object):

    def __init__(self, host=None, port=None, use_ssl=False):
        if host is None:
            host = FLAGS.melange_host
        if port is None:
            port = int(FLAGS.melange_port)
        self.host = host
        self.port = port
        self.use_ssl = use_ssl
        self.version = "v0.1"

    def get(self, path, params=None, headers=None):
        return self.do_request("GET", path, params=params, headers=headers)

    def post(self, path, body=None, headers=None):
        return self.do_request("POST", path, body=body, headers=headers)

    def delete(self, path, headers=None):
        return self.do_request("DELETE", path, headers=headers)

    def _get_connection(self):
        if self.use_ssl:
            return httplib.HTTPSConnection(self.host, self.port)
        else:
            return httplib.HTTPConnection(self.host, self.port)

    def do_request(self, method, path, body=None, headers=None, params=None):
        headers = headers or {}
        params = params or {}

        url = "/%s/%s.json" % (self.version, path)
        if params:
            url += "?%s" % urllib.urlencode(params)
        try:
            connection = self._get_connection()
            connection.request(method, url, body, headers)
            response = connection.getresponse()
            response_str = response.read()
            if response.status < 400:
                return response_str
            raise Exception(_("Server returned error: %s" % response_str))
        except (socket.error, IOError), e:
            raise Exception(_("Unable to connect to "
                            "server. Got error: %s" % e))

    def allocate_ip(self, network_id, vif_id,
                    project_id=None, mac_address=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""
        request_body = (json.dumps(dict(network=dict(mac_address=mac_address,
                                 tenant_id=project_id)))
                    if mac_address else None)
        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
           "interfaces/%(vif_id)s/ip_allocations" % locals())
        response = self.post(url, body=request_body,
                                    headers=json_content_type)
        return json.loads(response)['ip_addresses']

    def create_block(self, network_id, cidr,
                    project_id=None, dns1=None, dns2=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks" % locals()

        req_params = dict(ip_block=dict(cidr=cidr, network_id=network_id,
                                    type='private', dns1=dns1, dns2=dns2))
        self.post(url, body=json.dumps(req_params),
                                headers=json_content_type)

    def delete_block(self, block_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks/%(block_id)s" % locals()

        self.delete(url, headers=json_content_type)

    def get_blocks(self, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = "ipam%(tenant_scope)s/ip_blocks" % locals()

        response = self.get(url, headers=json_content_type)
        return json.loads(response)

    def get_allocated_ips(self, network_id, vif_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
           "interfaces/%(vif_id)s/ip_allocations" % locals())

        response = self.get(url, headers=json_content_type)
        return json.loads(response)['ip_addresses']

    def deallocate_ips(self, network_id, vif_id, project_id=None):
        tenant_scope = "/tenants/%s" % project_id if project_id else ""

        url = ("ipam%(tenant_scope)s/networks/%(network_id)s/"
           "interfaces/%(vif_id)s/ip_allocations" % locals())

        self.delete(url, headers=json_content_type)
