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

import socket

from oslo_config import cfg


console_opts = [
    cfg.ListOpt('console_allowed_origins',
                default=[],
                help='Allowed Origin header hostnames for access to console '
                     'proxy servers'),
    cfg.StrOpt('console_topic',
                default='console',
                help='The topic console proxy nodes listen on'),
    cfg.StrOpt('console_driver',
                default='nova.console.xvp.XVPConsoleProxy',
                help='Driver to use for the console proxy'),
    cfg.StrOpt('console_public_hostname',
                default=socket.gethostname(),
                help='Publicly visible name for this console host'),
]


def register_opts(conf):
    conf.register_opts(console_opts)


def list_opts():
    return {"DEFAULT": console_opts}
