#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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

from nova import flags
from nova.openstack.common import cfg


vnc_opts = [
    cfg.StrOpt('novncproxy_base_url',
               default='http://127.0.0.1:6080/vnc_auto.html',
               help='location of vnc console proxy, in the form '
                    '"http://127.0.0.1:6080/vnc_auto.html"'),
    cfg.StrOpt('xvpvncproxy_base_url',
               default='http://127.0.0.1:6081/console',
               help='location of nova xvp vnc console proxy, in the form '
                    '"http://127.0.0.1:6081/console"'),
    cfg.StrOpt('vncserver_listen',
               default='127.0.0.1',
               help='Ip address on which instance vncserversshould listen'),
    cfg.StrOpt('vncserver_proxyclient_address',
               default='127.0.0.1',
               help='the address to which proxy clients '
                    '(like nova-xvpvncproxy) should connect'),
    cfg.BoolOpt('vnc_enabled',
                default=True,
                help='enable vnc related features'),
    cfg.StrOpt('vnc_keymap',
               default='en-us',
               help='keymap for vnc'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(vnc_opts)
