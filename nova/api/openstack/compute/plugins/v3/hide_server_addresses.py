# Copyright 2012 OpenStack Foundation
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

"""Extension for hiding server addresses in certain states."""

from oslo_config import cfg

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.compute import vm_states

opts = [
    cfg.ListOpt('osapi_hide_server_address_states',
                default=[vm_states.BUILDING],
                help='List of instance states that should hide network info'),
]


CONF = cfg.CONF
CONF.register_opts(opts)

ALIAS = 'os-hide-server-addresses'
authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


class Controller(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(Controller, self).__init__(*args, **kwargs)
        hidden_states = CONF.osapi_hide_server_address_states

        # NOTE(jkoelker) _ is not considered uppercase ;)
        valid_vm_states = [getattr(vm_states, state)
                           for state in dir(vm_states)
                           if state.isupper()]
        self.hide_address_states = [state.lower()
                                    for state in hidden_states
                                    if state in valid_vm_states]

    def _perhaps_hide_addresses(self, instance, resp_server):
        if instance.get('vm_state') in self.hide_address_states:
            resp_server['addresses'] = {}

    @wsgi.extends
    def show(self, req, resp_obj, id):
        resp = resp_obj
        if not authorize(req.environ['nova.context']):
            return

        if 'server' in resp.obj and 'addresses' in resp.obj['server']:
            instance = req.get_db_instance(id)
            self._perhaps_hide_addresses(instance, resp.obj['server'])

    @wsgi.extends
    def detail(self, req, resp_obj):
        resp = resp_obj
        if not authorize(req.environ['nova.context']):
            return

        for server in list(resp.obj['servers']):
            if 'addresses' in server:
                instance = req.get_db_instance(server['id'])
                self._perhaps_hide_addresses(instance, server)


class HideServerAddresses(extensions.V3APIExtensionBase):
    """Support hiding server addresses in certain states."""

    name = 'HideServerAddresses'
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return [extensions.ControllerExtension(self, 'servers', Controller())]

    def get_resources(self):
        return []
