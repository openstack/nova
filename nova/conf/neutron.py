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

from keystoneauth1 import loading as ks_loading
from oslo_config import cfg

from nova.conf import utils as confutils


DEFAULT_SERVICE_TYPE = 'network'
NEUTRON_GROUP = 'neutron'

neutron_group = cfg.OptGroup(
    NEUTRON_GROUP,
    title='Neutron Options',
    help="""
Configuration options for neutron (network connectivity as a service).
""")

neutron_opts = [
    cfg.StrOpt('ovs_bridge',
         default='br-int',
         help="""
Default name for the Open vSwitch integration bridge.

Specifies the name of an integration bridge interface used by OpenvSwitch.
This option is only used if Neutron does not specify the OVS bridge name in
port binding responses.
"""),
    cfg.StrOpt('default_floating_pool',
        default='nova',
        help="""
Default name for the floating IP pool.

Specifies the name of floating IP pool used for allocating floating IPs. This
option is only used if Neutron does not specify the floating IP pool name in
port binding reponses.
"""),
    cfg.IntOpt('extension_sync_interval',
         default=600,
         min=0,
         help="""
Integer value representing the number of seconds to wait before querying
Neutron for extensions.  After this number of seconds the next time Nova
needs to create a resource in Neutron it will requery Neutron for the
extensions that it has loaded.  Setting value to 0 will refresh the
extensions with no wait.
"""),
    cfg.ListOpt('physnets',
        default=[],
        help="""
List of physnets present on this host.

For each *physnet* listed, an additional section,
``[neutron_physnet_$PHYSNET]``, will be added to the configuration file. Each
section must be configured with a single configuration option, ``numa_nodes``,
which should be a list of node IDs for all NUMA nodes this physnet is
associated with. For example::

    [neutron]
    physnets = foo, bar

    [neutron_physnet_foo]
    numa_nodes = 0

    [neutron_physnet_bar]
    numa_nodes = 0,1

Any *physnet* that is not listed using this option will be treated as having no
particular NUMA node affinity.

Tunnelled networks (VXLAN, GRE, ...) cannot be accounted for in this way and
are instead configured using the ``[neutron_tunnel]`` group. For example::

    [neutron_tunnel]
    numa_nodes = 1

Related options:

* ``[neutron_tunnel] numa_nodes`` can be used to configure NUMA affinity for
  all tunneled networks
* ``[neutron_physnet_$PHYSNET] numa_nodes`` must be configured for each value
  of ``$PHYSNET`` specified by this option
"""),
    cfg.IntOpt('http_retries',
               default=3,
               min=0,
               help="""
Number of times neutronclient should retry on any failed http call.

0 means connection is attempted only once. Setting it to any positive integer
means that on failure connection is retried that many times e.g. setting it
to 3 means total attempts to connect will be 4.

Possible values:

* Any integer value. 0 means connection is attempted only once
"""),
]

metadata_proxy_opts = [
    cfg.BoolOpt("service_metadata_proxy",
        default=False,
        help="""
When set to True, this option indicates that Neutron will be used to proxy
metadata requests and resolve instance ids. Otherwise, the instance ID must be
passed to the metadata request in the 'X-Instance-ID' header.

Related options:

* metadata_proxy_shared_secret
"""),
     cfg.StrOpt("metadata_proxy_shared_secret",
        default="",
        secret=True,
        help="""
This option holds the shared secret string used to validate proxy requests to
Neutron metadata requests. In order to be used, the
'X-Metadata-Provider-Signature' header must be supplied in the request.

Related options:

* service_metadata_proxy
"""),
]

ALL_OPTS = (neutron_opts + metadata_proxy_opts)


def register_opts(conf):
    conf.register_group(neutron_group)
    conf.register_opts(ALL_OPTS, group=neutron_group)
    confutils.register_ksa_opts(conf, neutron_group, DEFAULT_SERVICE_TYPE)


def register_dynamic_opts(conf):
    """Register dynamically-generated options and groups.

    This must be called by the service that wishes to use the options **after**
    the initial configuration has been loaded.
    """
    opt = cfg.ListOpt('numa_nodes', default=[], item_type=cfg.types.Integer())

    # Register the '[neutron_tunnel] numa_nodes' opt, implicitly
    # registering the '[neutron_tunnel]' group in the process. This could
    # be done statically but is done to avoid this group appearing in
    # nova.conf documentation while the other group does not.
    conf.register_opt(opt, group='neutron_tunnel')

    # Register the '[neutron_physnet_$PHYSNET] numa_nodes' opts, implicitly
    # registering the '[neutron_physnet_$PHYSNET]' groups in the process
    for physnet in conf.neutron.physnets:
        conf.register_opt(opt, group='neutron_physnet_%s' % physnet)


def list_opts():
    return {
        neutron_group: (
            ALL_OPTS +
            ks_loading.get_session_conf_options() +
            ks_loading.get_auth_common_conf_options() +
            ks_loading.get_auth_plugin_conf_options('password') +
            ks_loading.get_auth_plugin_conf_options('v2password') +
            ks_loading.get_auth_plugin_conf_options('v3password') +
            confutils.get_ksa_adapter_opts(DEFAULT_SERVICE_TYPE))
    }
