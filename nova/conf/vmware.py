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

import itertools

from oslo_config import cfg

vmware_group = cfg.OptGroup('vmware', title='VMWare Options')

vmwareapi_vif_opts = [
    cfg.StrOpt('vlan_interface',
               default='vmnic0',
               help='Physical ethernet adapter name for vlan networking'),
    cfg.StrOpt('integration_bridge',
               help='This option should be configured only when using the '
                    'NSX-MH Neutron plugin. This is the name of the '
                    'integration bridge on the ESXi. This should not be set '
                    'for any other Neutron plugin. Hence the default value '
                    'is not set.'),
]

vmware_utils_opts = [
    cfg.IntOpt('console_delay_seconds',
               help='Set this value if affected by an increased network '
                    'latency causing repeated characters when typing in '
                    'a remote console.'),
    cfg.StrOpt('serial_port_service_uri',
               help='Identifies the remote system that serial port traffic '
                    'will be sent to. If this is not set, no serial ports '
                    'will be added to the created VMs.'),
    cfg.StrOpt('serial_port_proxy_uri',
               help='Identifies a proxy service that provides network access '
                    'to the serial_port_service_uri. This option is ignored '
                    'if serial_port_service_uri is not specified.'),
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
                help='The PBM status.'),
    cfg.StrOpt('pbm_wsdl_location',
               help='PBM service WSDL file location URL. '
                    'e.g. file:///opt/SDK/spbm/wsdl/pbmService.wsdl '
                    'Not setting this will disable storage policy based '
                    'placement of instances.'),
    cfg.StrOpt('pbm_default_policy',
               help='The PBM default policy. If pbm_wsdl_location is set and '
                    'there is no defined storage policy for the specific '
                    'request then this policy will be used.'),
]

vimutil_opts = [
    cfg.IntOpt('maximum_objects',
               default=100,
               help='The maximum number of ObjectContent data '
                    'objects that should be returned in a single '
                    'result. A positive value will cause the '
                    'operation to suspend the retrieval when the '
                    'count of objects reaches the specified '
                    'maximum. The server may still limit the count '
                    'to something less than the configured value. '
                    'Any remaining objects may be retrieved with '
                    'additional requests.')
]

vmops_opts = [
    cfg.StrOpt('cache_prefix',
               help='The prefix for where cached images are stored. This is '
                    'NOT the full path - just a folder prefix. '
                    'This should only be used when a datastore cache should '
                    'be shared between compute nodes. Note: this should only '
                    'be used when the compute nodes have a shared file '
                    'system.'),
]

ALL_VMWARE_OPTS = list(itertools.chain(
                  vmwareapi_vif_opts,
                  vmware_utils_opts,
                  vmwareapi_opts,
                  spbm_opts,
                  vimutil_opts,
                  vmops_opts))


def register_opts(conf):
    conf.register_group(vmware_group)
    conf.register_opts(ALL_VMWARE_OPTS, group=vmware_group)


def list_opts():
    return {vmware_group: ALL_VMWARE_OPTS}
