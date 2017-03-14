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

from oslo_config import cfg

console_group = cfg.OptGroup('console',
    title='Console Options',
    help="""
Options under this group allow to tune the configuration of the console proxy
service.

Note: in configuration of every compute is a ``console_host`` option,
which allows to select the console proxy service to connect to.
""")

default_opts = [
    cfg.StrOpt('console_driver',
        default='nova.console.xvp.XVPConsoleProxy',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
This option no longer does anything. Previously this option had only two valid,
in-tree values: nova.console.xvp.XVPConsoleProxy and
nova.console.fake.FakeConsoleProxy. The latter of these was only used in tests
and has since been replaced.
""",
        help="""
nova-console-proxy is used to set up multi-tenant VM console access.
This option allows pluggable driver program for the console session
and represents driver to use for the console proxy.

Possible values:

* A string representing fully classified class name of console driver.
"""),
    cfg.StrOpt('console_topic',
        default='console',
        deprecated_for_removal=True,
        deprecated_since='15.0.0',
        deprecated_reason="""
There is no need to let users choose the RPC topic for all services - there
is little gain from this. Furthermore, it makes it really easy to break Nova
by using this option.
""",
        help="""
Represents the message queue topic name used by nova-console
service when communicating via the AMQP server. The Nova API uses a message
queue to communicate with nova-console to retrieve a console URL for that
host.

Possible values:

* A string representing topic exchange name
""")
]

console_opts = [
    cfg.ListOpt('allowed_origins',
        default=[],
        deprecated_group='DEFAULT',
        deprecated_name='console_allowed_origins',
        help="""
Adds list of allowed origins to the console websocket proxy to allow
connections from other origin hostnames.
Websocket proxy matches the host header with the origin header to
prevent cross-site requests. This list specifies if any there are
values other than host are allowed in the origin header.

Possible values:

* A list where each element is an allowed origin hostnames, else an empty list
"""),
]


def register_opts(conf):
    conf.register_group(console_group)
    conf.register_opts(console_opts, group=console_group)
    conf.register_opts(default_opts)


def list_opts():
    return {
        console_group: console_opts,
        'DEFAULT': default_opts,
    }
