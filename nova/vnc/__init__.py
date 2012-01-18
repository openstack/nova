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


FLAGS = flags.FLAGS
flags.DEFINE_string('novncproxy_base_url',
                   'http://127.0.0.1:6080/vnc_auto.html',
                   'location of vnc console proxy, \
                    in the form "http://127.0.0.1:6080/vnc_auto.html"')
flags.DEFINE_string('xvpvncproxy_base_url',
                   'http://127.0.0.1:6081/console',
                   'location of nova xvp vnc console proxy, \
                    in the form "http://127.0.0.1:6081/console"')
flags.DEFINE_string('vncserver_listen', '127.0.0.1',
                    'Ip address on which instance vncservers\
                     should listen')
flags.DEFINE_string('vncserver_proxyclient_address', '127.0.0.1',
                    'the address to which proxy clients \
                    (like nova-xvpvncproxy) should connect')
flags.DEFINE_bool('vnc_enabled', True,
                  'enable vnc related features')
flags.DEFINE_string('vnc_keymap', 'en-us',
                   'keymap for vnc')
