# Copyright 2013 IBM Corp.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Extended Ips API extension."""

import itertools

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi

authorize = extensions.soft_extension_authorizer('compute', 'extended_ips_mac')


class ExtendedIpsMacController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedIpsMacController, self).__init__(*args, **kwargs)

    def _extend_server(self, context, server, instance):
        key = "%s:mac_addr" % Extended_ips_mac.alias
        networks = common.get_networks_for_instance(context, instance)
        for label, network in networks.items():
            # NOTE(vish): ips are hidden in some states via the
            #             hide_server_addresses extension.
            if label in server['addresses']:
                all_ips = itertools.chain(network["ips"],
                                          network["floating_ips"])
                for i, ip in enumerate(all_ips):
                    server['addresses'][label][i][key] = ip['mac_address']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(context, server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(context, server, db_instance)


class Extended_ips_mac(extensions.ExtensionDescriptor):
    """Adds mac address parameter to the ip list."""

    name = "ExtendedIpsMac"
    alias = "OS-EXT-IPS-MAC"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "extended_ips_mac/api/v1.1")
    updated = "2013-03-07T00:00:00Z"

    def get_controller_extensions(self):
        controller = ExtendedIpsMacController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
