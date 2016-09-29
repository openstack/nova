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
                help="""
Adds list of allowed origins to the console websocket proxy to allow
connections from other origin hostnames.
Websocket proxy matches the host header with the origin header to
prevent cross-site requests. This list specifies if any there are
values other than host are allowed in the origin header.

Possible values

  * An empty list (default) or list of allowed origin hostnames.
"""),

# TODO(pumaranikar): We can deprecate this option.
    cfg.StrOpt('console_topic',
                default='console',
                help="""
Represents the message queue topic name used by nova-console
service when communicating via the AMQP server. The Nova API uses a message
queue to communicate with nova-console to retrieve a console URL for that
host.

Possible values

  * 'console' (default) or any string representing topic exchange name.
"""),

# TODO(pumaranikar): Move this config to stevedore plugin system.
    cfg.StrOpt('console_driver',
                default='nova.console.xvp.XVPConsoleProxy',
                help="""
Nova-console proxy is used to set up multi-tenant VM console access.
This option allows pluggable driver program for the console session
and represents driver to use for the console proxy.

Possible values

  * 'nova.console.xvp.XVPConsoleProxy' (default) or
    a string representing fully classified class name of console driver.
"""),

    cfg.StrOpt('console_public_hostname',
                default=socket.gethostname(),
                help="""
Publicly visible name for this console host.

Possible values

  * Current hostname (default) or any string representing hostname.
"""),
]


def register_opts(conf):
    conf.register_opts(console_opts)


# TODO(pumaranikar): We can consider moving these options to console group
# and renaming them all to drop console bit.
def list_opts():
    return {"DEFAULT": console_opts}
