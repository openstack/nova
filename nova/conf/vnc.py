# Copyright (c) 2010 OpenStack Foundation
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

vnc_group = cfg.OptGroup(
    'vnc',
    title='VNC options')

enabled = cfg.BoolOpt(
    'enabled',
    default=True,
    help='Enable VNC related features',
    deprecated_group='DEFAULT',
    deprecated_name='vnc_enabled')

keymap = cfg.StrOpt(
    'keymap',
    default='en-us',
    help='Keymap for VNC',
    deprecated_group='DEFAULT',
    deprecated_name='vnc_keymap')

vncserver_listen = cfg.StrOpt(
    'vncserver_listen',
    default='127.0.0.1',
    help='IP address on which instance vncservers should listen',
    deprecated_group='DEFAULT')

vncserver_proxyclient_address = cfg.StrOpt(
    'vncserver_proxyclient_address',
    default='127.0.0.1',
    help='The address to which proxy clients '
         '(like nova-xvpvncproxy) should connect',
    deprecated_group='DEFAULT')

novncproxy_host = cfg.StrOpt(
    'novncproxy_host',
    default='0.0.0.0',
    help='Host on which to listen for incoming requests',
    deprecated_group='DEFAULT')

novncproxy_port = cfg.IntOpt(
    'novncproxy_port',
    default=6080,
    min=1,
    max=65535,
    help='Port on which to listen for incoming requests',
    deprecated_group='DEFAULT')

xvpvncproxy_host = cfg.StrOpt(
    'xvpvncproxy_host',
    default='0.0.0.0',
    help='Address that the XVP VNC console proxy should bind to',
    deprecated_group='DEFAULT')

xvpvncproxy_port = cfg.IntOpt(
    'xvpvncproxy_port',
    default=6081,
    min=1,
    max=65535,
    help='Port that the XVP VNC console proxy should bind to',
    deprecated_group='DEFAULT')

novncproxy_base_url = cfg.StrOpt(
    'novncproxy_base_url',
    default='http://127.0.0.1:6080/vnc_auto.html',
    help='Location of VNC console proxy, in the form '
         '"http://127.0.0.1:6080/vnc_auto.html"',
    deprecated_group='DEFAULT')

xvpvncproxy_base_url = cfg.StrOpt(
    'xvpvncproxy_base_url',
    default='http://127.0.0.1:6081/console',
    help='Location of XVP VNC console proxy, in the form '
         '"http://127.0.0.1:6081/console"',
    deprecated_group='DEFAULT')

ALL_OPTS = [
    enabled,
    keymap,
    vncserver_listen,
    vncserver_proxyclient_address,
    novncproxy_host,
    novncproxy_port,
    xvpvncproxy_host,
    xvpvncproxy_port,
    novncproxy_base_url,
    xvpvncproxy_base_url]

CLI_OPTS = [
    novncproxy_host,
    novncproxy_port]


def register_opts(conf):
    conf.register_group(vnc_group)
    conf.register_opts(ALL_OPTS, group=vnc_group)


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=vnc_group)


def list_opts():
    return {vnc_group: ALL_OPTS}
