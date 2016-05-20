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

upgrade_group = cfg.OptGroup('upgrade_levels',
        title='Upgrade levels Options')

rpcapi_cap_cells_opt = cfg.StrOpt('cells',
        help="""
Cells version

Cells client-side RPC API version. Use this option to set a version
cap for messages sent to local cells services.

Possible values:

* None: This is the default value.
* grizzly: message version 1.6.
* havana: message version 1.24.
* icehouse: message version 1.27.
* juno: message version 1.29.
* kilo: message version 1.34.
* liberty: message version 1.37.

Services which consume this:

* nova-cells

Related options:

* None
""")

rpcapi_cap_intercell_opt = cfg.StrOpt('intercell',
        help="""
Intercell version

Intercell RPC API is the client side of the Cell<->Cell RPC API.
Use this option to set a version cap for messages sent between
cells services.

Possible values:

* None: This is the default value.
* grizzly: message version 1.0.

Services which consume this:

* nova-cells

Related options:

* None
""")

rpcapi_cap_cert_opt = cfg.StrOpt("cert",
        help="""

Specifies the maximum version for messages sent from cert services. This should
be the minimum value that is supported by all of the deployed cert services.

Possible values:

Any valid OpenStack release name, in lower case, such as 'mitaka' or 'liberty'.
Alternatively, it can be any string representing a version number in the format
'N.N'; for example, possible values might be '1.12' or '2.0'.

Services which consume this:

* nova-cert

Related options:

* None
""")

rpcapi_cap_compute_opt = cfg.StrOpt('compute',
        help='Set a version cap for messages sent to compute services. '
             'Set this option to "auto" if you want to let the compute RPC '
             'module automatically determine what version to use based on '
             'the service versions in the deployment. '
             'Otherwise, you can set this to a specific version to pin this '
             'service to messages at a particular level. '
             'All services of a single type (i.e. compute) should be '
             'configured to use the same version, and it should be set '
             'to the minimum commonly-supported version of all those '
             'services in the deployment.')

rpcapi_cap_scheduler_opt = cfg.StrOpt("scheduler",
        help="""
Sets a version cap (limit) for messages sent to scheduler services. In the
situation where there were multiple scheduler services running, and they were
not being upgraded together, you would set this to the lowest deployed version
to guarantee that other services never send messages that any of your running
schedulers cannot understand.

This is rarely needed in practice as most deployments run a single scheduler.
It exists mainly for design compatibility with the other services, such as
compute, which are routinely upgraded in a rolling fashion.

Services that use this:

* nova-compute, nova-conductor

Related options:

* None
""")

rpcapi_cap_conductor_opt = cfg.StrOpt('conductor',
        help='Set a version cap for messages sent to conductor services')

rpcapi_cap_console_opt = cfg.StrOpt('console',
        help='Set a version cap for messages sent to console services')

rpcapi_cap_consoleauth_opt = cfg.StrOpt('consoleauth',
        help='Set a version cap for messages sent to consoleauth services')

rpcapi_cap_network_opt = cfg.StrOpt('network',
        help='Set a version cap for messages sent to network services')

rpcapi_cap_baseapi_opt = cfg.StrOpt('baseapi',
        help='Set a version cap for messages sent to the base api in any '
             'service')

ALL_OPTS = [rpcapi_cap_cells_opt,
            rpcapi_cap_intercell_opt,
            rpcapi_cap_cert_opt,
            rpcapi_cap_compute_opt,
            rpcapi_cap_scheduler_opt,
            rpcapi_cap_conductor_opt,
            rpcapi_cap_console_opt,
            rpcapi_cap_consoleauth_opt,
            rpcapi_cap_network_opt,
            rpcapi_cap_baseapi_opt]


def register_opts(conf):
    conf.register_group(upgrade_group)
    conf.register_opts(ALL_OPTS, group=upgrade_group)


def list_opts():
    return {upgrade_group: ALL_OPTS}
