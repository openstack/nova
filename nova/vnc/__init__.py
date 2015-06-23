#!/usr/bin/env python
# Copyright (c) 2010 OpenStack Foundation
# All Rights Reserved.
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

"""Module for VNC Proxying."""

from oslo_config import cfg


vnc_opts = [
    cfg.StrOpt('novncproxy_base_url',
               default='http://127.0.0.1:6080/vnc_auto.html',
               help='Location of VNC console proxy, in the form '
                    '"http://127.0.0.1:6080/vnc_auto.html"',
               deprecated_group='DEFAULT',
               deprecated_name='novncproxy_base_url'),
    cfg.StrOpt('xvpvncproxy_base_url',
               default='http://127.0.0.1:6081/console',
               help='Location of nova xvp VNC console proxy, in the form '
                    '"http://127.0.0.1:6081/console"',
               deprecated_group='DEFAULT',
               deprecated_name='xvpvncproxy_base_url'),
    cfg.StrOpt('vncserver_listen',
               default='127.0.0.1',
               help='IP address on which instance vncservers should listen',
               deprecated_group='DEFAULT',
               deprecated_name='vncserver_listen'),
    cfg.StrOpt('vncserver_proxyclient_address',
               default='127.0.0.1',
               help='The address to which proxy clients '
                    '(like nova-xvpvncproxy) should connect',
               deprecated_group='DEFAULT',
               deprecated_name='vncserver_proxyclient_address'),
    cfg.BoolOpt('enabled',
                default=True,
                help='Enable VNC related features',
                deprecated_group='DEFAULT',
                deprecated_name='vnc_enabled'),
    cfg.StrOpt('keymap',
               default='en-us',
               help='Keymap for VNC',
               deprecated_group='DEFAULT',
               deprecated_name='vnc_keymap'),
    ]

CONF = cfg.CONF
CONF.register_opts(vnc_opts, group='vnc')
