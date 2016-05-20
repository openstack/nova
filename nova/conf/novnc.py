# Copyright (c) 2016 OpenStack Foundation
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

novnc_opts = [
    cfg.StrOpt('record',
                help='This is the filename that will be used for storing '
                     'websocket frames received and sent by a proxy service '
                     '(like VNC, spice, serial) running on this host. If this '
                     'is not set (default), no recording will be done.'),
    cfg.BoolOpt('daemon',
                default=False,
                help='Become a daemon (background process)'),
    cfg.BoolOpt('ssl_only',
                default=False,
                help='Disallow non-encrypted connections'),
    cfg.BoolOpt('source_is_ipv6',
                default=False,
                help='Source is ipv6'),
    cfg.StrOpt('cert',
               default='self.pem',
               help='SSL certificate file'),
    cfg.StrOpt('key',
               help='SSL key file (if separate from cert)'),
    cfg.StrOpt('web',
               default='/usr/share/spice-html5',
               help='Run webserver on same port. Serve files from DIR.'),
    ]


def register_opts(conf):
    conf.register_opts(novnc_opts)


def register_cli_opts(conf):
    conf.register_cli_opts(novnc_opts)


def list_opts():
    return {'DEFAULT': novnc_opts}
