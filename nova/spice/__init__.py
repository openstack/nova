#!/usr/bin/env python
# Copyright (c) 2012 Red Hat, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Module for SPICE Proxying."""

from oslo_config import cfg


spice_opts = [
    cfg.StrOpt('html5proxy_base_url',
               default='http://127.0.0.1:6082/spice_auto.html',
               help='Location of spice HTML5 console proxy, in the form '
                    '"http://127.0.0.1:6082/spice_auto.html"'),
    cfg.StrOpt('server_listen',
               default='127.0.0.1',
               help='IP address on which instance spice server should listen'),
    cfg.StrOpt('server_proxyclient_address',
               default='127.0.0.1',
               help='The address to which proxy clients '
                    '(like nova-spicehtml5proxy) should connect'),
    cfg.BoolOpt('enabled',
                default=False,
                help='Enable spice related features'),
    cfg.BoolOpt('agent_enabled',
                default=True,
                help='Enable spice guest agent support'),
    cfg.StrOpt('keymap',
               default='en-us',
               help='Keymap for spice'),
    ]

CONF = cfg.CONF
CONF.register_opts(spice_opts, group='spice')
