# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg

GROUP_NAME = 'spice'
spice_opt_group = cfg.OptGroup(GROUP_NAME)


enabled_opt = cfg.BoolOpt('enabled',
        default=False,
        help="""
Enable spice related features.
""")


agent_enabled_opt = cfg.BoolOpt('agent_enabled',
        default=True,
        help="""
Enable the spice guest agent support.
""")


html5proxy_base_url_opt = cfg.StrOpt('html5proxy_base_url',
        default='http://127.0.0.1:6082/spice_auto.html',
        help="""
Location of spice HTML5 console proxy, in the form
"http://127.0.0.1:6082/spice_auto.html"
""")


html5proxy_host_opt = cfg.StrOpt('html5proxy_host',
        default='0.0.0.0',
        help="""
Host on which to listen for incoming requests
""")


html5proxy_port_opt = cfg.IntOpt('html5proxy_port',
        default=6082,
        min=1,
        max=65535,
        help="""
Port on which to listen for incoming requests
""")


server_listen_opt = cfg.StrOpt('server_listen',
        default='127.0.0.1',
        help="""
IP address on which instance spice server should listen
""")


server_proxyclient_address_opt = cfg.StrOpt('server_proxyclient_address',
        default='127.0.0.1',
        help="""
The address to which proxy clients (like nova-spicehtml5proxy) should connect
""")


keymap_opt = cfg.StrOpt('keymap',
        default='en-us',
        help="""
Keymap for spice
""")


ALL_OPTS = [html5proxy_base_url_opt,
            server_listen_opt,
            server_proxyclient_address_opt,
            enabled_opt,
            agent_enabled_opt,
            keymap_opt,
            html5proxy_host_opt,
            html5proxy_port_opt]


CLI_OPTS = [html5proxy_host_opt,
            html5proxy_port_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group=spice_opt_group)


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=spice_opt_group)


def list_opts():
    return {spice_opt_group: ALL_OPTS}
