# Copyright (c) 2016 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

debugger_group = cfg.OptGroup('remote_debug',
    title='debugger options')

host = cfg.StrOpt('host',
    help='Debug host (IP or name) to connect. Note '
    'that using the remote debug option changes how '
    'Nova uses the eventlet library to support async IO. '
    'This could result in failures that do not occur '
    'under normal operation. Use at your own risk.')

port = cfg.IntOpt('port',
    min=1,
    max=65535,
    help='Debug port to connect. Note '
    'that using the remote debug option changes how '
    'Nova uses the eventlet library to support async IO. '
    'This could result in failures that do not occur '
    'under normal operation. Use at your own risk.')

CLI_OPTS = [host, port]


def register_cli_opts(conf):
    conf.register_cli_opts(CLI_OPTS, group=debugger_group)


def list_opts():
    return {debugger_group: CLI_OPTS}
