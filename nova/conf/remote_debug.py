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

CLI_OPTS = [
    cfg.HostAddressOpt('host',
        help="""
Debug host (IP or name) to connect to.

This command line parameter is used when you want to connect to a nova service
via a debugger running on a different host.

Note that using the remote debug option changes how nova uses the eventlet
library to support async IO. This could result in failures that do not occur
under normal operation. Use at your own risk.

Possible Values:

* IP address of a remote host as a command line parameter to a nova service.
  For example::

    nova-compute --config-file /etc/nova/nova.conf \
      --remote_debug-host <IP address of the debugger>
"""),
    cfg.PortOpt('port',
        help="""
Debug port to connect to.

This command line parameter allows you to specify the port you want to use to
connect to a nova service via a debugger running on different host.

Note that using the remote debug option changes how nova uses the eventlet
library to support async IO. This could result in failures that do not occur
under normal operation. Use at your own risk.

Possible Values:

* Port number you want to use as a command line parameter to a nova service.
  For example::

    nova-compute --config-file /etc/nova/nova.conf \
      --remote_debug-host <IP address of the debugger> \
      --remote_debug-port <port debugger is listening on>.
"""),
]


def register_cli_opts(conf):
    conf.register_group(debugger_group)
    conf.register_cli_opts(CLI_OPTS, group=debugger_group)


def list_opts():
    return {debugger_group: CLI_OPTS}
