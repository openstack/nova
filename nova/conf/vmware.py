# needs:fix_opt_description
# needs:check_deprecation_status
# needs:check_opt_group_and_type
# needs:fix_opt_description_indentation
# needs:fix_opt_registration_consistency


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

vmware_group = cfg.OptGroup('vmware', title='VMWare Options')

vmwareapi_vif_opts = [
    cfg.StrOpt('vlan_interface',
               default='vmnic0',
               help="""
This option specifies the physical ethernet adapter name for VLAN
networking.

Set the vlan_interface configuration option to match the ESX host
interface that handles VLAN-tagged VM traffic.

Possible values:

* Any valid string representing VLAN interface name
"""),
    cfg.StrOpt('integration_bridge',
               help="""
This option should be configured only when using the NSX-MH Neutron
plugin. This is the name of the integration bridge on the ESXi server
or host. This should not be set for any other Neutron plugin. Hence
the default value is not set.

Possible values:

* Any valid string representing the name of the integration bridge
"""),
]

vmware_utils_opts = [
    cfg.IntOpt('console_delay_seconds',
               min=0,
               help="""
Set this value if affected by an increased network latency causing
repeated characters when typing in a remote console.
"""),
    cfg.StrOpt('serial_port_service_uri',
               help="""
Identifies the remote system where the serial port traffic will
be sent.

This option adds a virtual serial port which sends console output to
a configurable service URI. At the service URI address there will be
virtual serial port concentrator that will collect console logs.
If this is not set, no serial ports will be added to the created VMs.

Possible values:

* Any valid URI
"""),
    cfg.StrOpt('serial_port_proxy_uri',
               help="""
Identifies a proxy service that provides network access to the
serial_port_service_uri.

Possible values:

* Any valid URI

Related options:
This option is ignored if serial_port_service_uri is not specified.
* serial_port_service_uri
"""),
]

vmwareapi_opts = [
    cfg.StrOpt('host_ip',
               help='Hostname or IP address for connection to VMware '
                    'vCenter host.'),
    cfg.PortOpt('host_port',
                default=443,
                help='Port for connection to VMware vCenter host.'),
    cfg.StrOpt('host_username',
               help='Username for connection to VMware vCenter host.'),
    cfg.StrOpt('host_password',
               help='Password for connection to VMware vCenter host.',
               secret=True),
    cfg.StrOpt('ca_file',
               help='Specify a CA bundle file to use in verifying the '
                    'vCenter server certificate.'),
    cfg.BoolOpt('insecure',
                default=False,
                help='If true, the vCenter server certificate is not '
                     'verified. If false, then the default CA truststore is '
                     'used for verification. This option is ignored if '
                     '"ca_file" is set.'),
    cfg.StrOpt('cluster_name',
               help='Name of a VMware Cluster ComputeResource.'),
    cfg.StrOpt('datastore_regex',
               help='Regex to match the name of a datastore.'),
    cfg.FloatOpt('task_poll_interval',
                 default=0.5,
                 help='The interval used for polling of remote tasks.'),
    cfg.IntOpt('api_retry_count',
               default=10,
               help='The number of times we retry on failures, e.g., '
                    'socket error, etc.'),
    cfg.PortOpt('vnc_port',
                default=5900,
                help='VNC starting port'),
    cfg.IntOpt('vnc_port_total',
               default=10000,
               help='Total number of VNC ports'),
    cfg.BoolOpt('use_linked_clone',
                default=True,
                help='Whether to use linked clone'),
    cfg.StrOpt('wsdl_location',
               help='Optional VIM Service WSDL Location '
                    'e.g http://<server>/vimService.wsdl. '
                    'Optional over-ride to default location for bug '
                    'work-arounds')
]

spbm_opts = [
    cfg.BoolOpt('pbm_enabled',
                default=False,
                help="""
This option enables or disables storage policy based placement
of instances.

Related options:

* pbm_default_policy
"""),
    cfg.StrOpt('pbm_wsdl_location',
               help="""
This option specifies the PBM service WSDL file location URL.

Setting this will disable storage policy based placement
of instances.

Possible values:

* Any valid file path
  e.g file:///opt/SDK/spbm/wsdl/pbmService.wsdl
"""),
    cfg.StrOpt('pbm_default_policy',
               help="""
This option specifies the default policy to be used.

If pbm_enabled is set and there is no defined storage policy for the
specific request, then this policy will be used.

Possible values:

* Any valid storage policy such as VSAN default storage policy

Related options:

* pbm_enabled
"""),
]

vmops_opts = [
    cfg.IntOpt('maximum_objects',
               min=0,
               default=100,
               help="""
This option specifies the limit on the maximum number of objects to
return in a single result.

A positive value will cause the operation to suspend the retrieval
when the count of objects reaches the specified limit. The server may
still limit the count to something less than the configured value.
Any remaining objects may be retrieved with additional requests.
"""),
    cfg.StrOpt('cache_prefix',
               help="""
This option adds a prefix to the folder where cached images are stored

This is not the full path - just a folder prefix. This should only be
used when a datastore cache is shared between compute nodes.

Note: This should only be used when the compute nodes are running on same
host or they have a shared file system.

Possible values:

* Any string representing the cache prefix to the folder
""")
]

ALL_VMWARE_OPTS = (vmwareapi_vif_opts +
                  vmware_utils_opts +
                  vmwareapi_opts +
                  spbm_opts +
                  vmops_opts)


def register_opts(conf):
    conf.register_group(vmware_group)
    conf.register_opts(ALL_VMWARE_OPTS, group=vmware_group)


def list_opts():
    return {vmware_group: ALL_VMWARE_OPTS}
