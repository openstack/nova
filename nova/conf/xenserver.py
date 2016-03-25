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

xenserver_group = cfg.OptGroup('xenserver', title='Xenserver Options')

xenapi_agent_opts = [
    cfg.IntOpt('agent_timeout',
               default=30,
               help="""
               Number of seconds to wait for agent's reply to a request.

               Nova configures/performs certain administrative actions on a
               server with the help of an agent that's installed on the server.
               The communication between Nova and the agent is achieved via
               sharing messages, called records, over xenstore, a shared
               storage across all the domains on a Xenserver host.
               Operations performed by the agent on behalf of nova are:
               'version',' key_init', 'password','resetnetwork','inject_file',
               and 'agentupdate'.

               To perform one of the above operations, the xapi 'agent' plugin
               writes the command and its associated parameters to a certain
               location known to the domain and awaits response. On being
               notified of the message, the agent performs appropriate actions
               on the server and writes the result back to xenstore.
               This result is then read by the xapi 'agent' plugin to
               determine the success/failure of the operation.

               This config option determines how long the xapi 'agent' plugin
               shall wait to read the response off of xenstore for a given
               request/command. If the agent on the instance fails to write
               the result in this time period, the operation is considered to
               have timed out.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * ``agent_version_timeout``
               * ``agent_resetnetwork_timeout``

               """),
    cfg.IntOpt('agent_version_timeout',
               default=300,
               help="""
               Number of seconds to wait for agent't reply to version request.

               This indicates the amount of time xapi 'agent' plugin waits
               for the agent to respond to the 'version' request specifically.
               The generic timeout for agent communication ``agent_timeout``
               is ignored in this case.

               During the build process the 'version' request is used to
               determine if the agent is available/operational to perform
               other requests such as 'resetnetwork', 'password', 'key_init'
               and 'inject_file'. If the 'version' call fails, the other
               configuration is skipped. So, this configuration option can
               also be interpreted as time in which agent is expected to be
               fully operational.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * None

               """),
    cfg.IntOpt('agent_resetnetwork_timeout',
               default=60,
               help="""
               Number of seconds to wait for agent's reply to resetnetwork
               request.

               This indicates the amount of time xapi 'agent' plugin waits
               for the agent to respond to the 'resetnetwork' request
               specifically. The generic timeout for agent communication
               ``agent_timeout`` is ignored in this case.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * Any positive integer

               Related options:
               * None

               """),
    cfg.StrOpt('agent_path',
               default='usr/sbin/xe-update-networking',
               help="""
               Path to locate guest agent on the server.

               Specifies the path in which the XenAPI guest agent should be
               located. If the agent is present, network configuration is not
               injected into the image.
               Used if compute_driver=xenapi.XenAPIDriver and
               flat_injected=True.

               Services which consume this:
               * ``nova-compute``

               Possible values:
               * A valid path

               Related options:
               * ``flat_injected``
               * ``compute_driver``

               """),
    cfg.BoolOpt('disable_agent',
                default=False,
                help="""
                Disables the use of XenAPI agent.

                This configuration option suggests whether the use of agent
                should be enabled or not regardless of what image properties
                are present. Image properties have an effect only when this
                is set to ``True``. Read description of config option
                ``use_agent_default`` for more information.

                Services which consume this:
                * ``nova-compute``

                Possible values:
                * True
                * False

                Related options:
                * ``use_agent_default``

                """),
    cfg.BoolOpt('use_agent_default',
                default=False,
                help="""
                Whether or not to use the agent by default when its usage is
                enabled but not indicated by the image.

                The use of XenAPI agent can be disabled altogether using the
                configuration option ``disable_agent``. However, if it is not
                disabled, the use of an agent can still be controlled by the
                image in use through one of its properties,
                ``xenapi_use_agent``. If this property is either not present
                or specified incorrectly on the image, the use of agent is
                determined by this configuration option.

                Note that if this configuration is set to ``True`` when the
                agent is not present, the boot times will increase
                significantly.

                Services which consume this:
                * ``nova-compute``

                Possible values:
                * True
                * False

                Related options:
                * ``disable_agent``

                """),
]

ALL_XENSERVER_OPTS = xenapi_agent_opts


def register_opts(conf):
    conf.register_group(xenserver_group)
    conf.register_opts(ALL_XENSERVER_OPTS, group=xenserver_group)


def list_opts():
    return {xenserver_group.name: ALL_XENSERVER_OPTS}
