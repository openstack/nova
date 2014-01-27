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

from oslo.config import cfg


vnc_opts = [
    cfg.StrOpt('novncproxy_base_url',
               default='http://127.0.0.1:6080/vnc_auto.html',
               help='Location of VNC console proxy, in the form '
                    '"http://127.0.0.1:6080/vnc_auto.html"'),
    cfg.StrOpt('xvpvncproxy_base_url',
               default='http://127.0.0.1:6081/console',
               help='Location of nova xvp VNC console proxy, in the form '
                    '"http://127.0.0.1:6081/console"'),
    cfg.StrOpt('vncserver_listen',
               default='127.0.0.1',
               help='IP address on which instance vncservers should listen'),
    cfg.StrOpt('vncserver_proxyclient_address',
               default='127.0.0.1',
               help='The address to which proxy clients '
                    '(like nova-xvpvncproxy) should connect'),
    cfg.BoolOpt('vnc_enabled',
                default=True,
                help='Enable VNC related features'),
    cfg.StrOpt('vnc_keymap',
               default='en-us',
               help='Keymap for VNC'),
    ]

CONF = cfg.CONF
CONF.register_opts(vnc_opts)
