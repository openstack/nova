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

vmware_group = cfg.OptGroup('vmware',
                            title='VMWare Options',
                            help="""
Related options:
Following options must be set in order to launch VMware-based
virtual machines.

* compute_driver: Must use vmwareapi.VMwareVCDriver.
* vmware.host_username
* vmware.host_password
* vmware.cluster_name
""")

vmwareapi_vif_opts = [
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
    # NOTE(takashin): 'serial_port_service_uri' can be non URI format.
    # See https://opendev.org/x/vmware-vspc/src/branch/master/README.rst
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
    cfg.URIOpt('serial_port_proxy_uri',
               schemes=['telnet', 'telnets'],
               help="""
Identifies a proxy service that provides network access to the
serial_port_service_uri.

Possible values:

* Any valid URI (The scheme is 'telnet' or 'telnets'.)

Related options:
This option is ignored if serial_port_service_uri is not specified.
* serial_port_service_uri
"""),
    cfg.BoolOpt('serial_port_connected_default',
                default=True,
                help="""
Configure, whether the added serial port should be connected by default

This option can be used to enable the possibility to collect logs only for
specific VMs, by reconfiguring and rebooting them in the vCenter.

Related options:
This option is ignored if serial_port_service_uri is not specified.
* serial_port_service_uri
"""),
    cfg.StrOpt('serial_log_dir',
               default='/opt/vmware/vspc',
               help="""
Specifies the directory where the Virtual Serial Port Concentrator is
storing console log files. It should match the 'serial_log_dir' config
value of VSPC.
"""),
    cfg.StrOpt('serial_log_uri',
               help="""
Specifies the server where the Virtual Serial Port Concentrator is
storing console log files and responding to get requests.
If defined it will override serial_log_dir.
"""),
    cfg.BoolOpt('reserve_all_memory',
                default=False,
                help="""
If true, it is not possible to over-commit memory in the vCenter, but there's
also no swap file pre-created on the ephemeral storage. Swap still works, but
is hot-created.

For big VMs as determined by the `bigvm_mb` setting, this setting is not used.
Big VMs always reserve all their memory.
"""),
    cfg.IntOpt('memory_reservation_cluster_hosts_max_fail',
                default=0,
                min=0,
                help="""
Allow reserving instance memory while at least n hypervisors of memory remain
unreserved in the cluster. This is a safety margin so a certain number of
cluster hypervisors are allowed to fail. If more memory would be reserved and
all the anticipated HV failures occurred, existing VMs with reserved memory
would no longer be able to start.

This setting applies to VMs with flavors which have a nonzero extra_spec
"resources:CUSTOM_MEMORY_RESERVABLE_MB" set.

The default value of 0 also leads to this setting being ignored and falling
back on `memory_reservation_max_ratio_fallback`.
"""),
    cfg.FloatOpt('memory_reservation_max_ratio_fallback',
        default=1.0,
        help="""
Allow reserving instance memory up to a maximum ratio in the cluster. This is a
safety margin so a certain ratio of cluster hypervisors are allowed to fail. If
more memory than that would be reserved and all the anticipated HV failures
occurred, existing VMs with reserved memory would no longer be able to start.

This setting applies to VMs with flavors which have a nonzero extra_spec
"resources:CUSTOM_MEMORY_RESERVABLE_MB" set.

This is a fallback when the `memory_reservation_cluster_hosts_max_fail` config
is set to 0.
"""),
    cfg.StrOpt('hostgroup_reservations_json_file',
        help="""
Specifies the path to a JSON file containing vcpus and memory reservations per
hostgroup. HVs found to be in a hostgroup specified in this dict will report
the amount of vcpus/memory as reserved to the placement API. This enables us to
specify different reservations for HANA-used HVs and for "normal" HVs. The
special key `__default__` holds values applied if there is no specification for
an HV's hostgroup. It defaults to 0.

There are two ways to specify a hostgroup's values: as static numbers and as
percent. Static numbers take precedence over percent if both are present.
Additionally, values are inherited from the `__default__` group if not present
for a group. To prohibt inheriting a value, explicitly set it to `null`.

Example configuration could be:
 {"__default__": {"memory_percent": 10, "vcpus": 10},
  "hana_hosts": {"memory_mb": 16384, "vcpus": 5},
  "normal_hosts": {"vcpus": null, "vcpus_percent": 2}}

If there are cluster-wide reservations defined via `reserved_host_cpus` or
`reserved_host_memory_mb`, they are added to the sum of the hostgroup-defined
ones.

NOTE: Percentage values will be rounded down to the next full vcpu/MB.
"""),
    cfg.StrOpt('special_spawning_vm_group',
        default='bigvm_free_host_antiaffinity_vmgroup',
        help="""
For spawning a VM on a prepared empty host, we need all other VMs to be in a
DRS VM group that prohibits them from running on the prepared host. This
setting configures the name of that VM group.
"""),
    cfg.BoolOpt('mirror_instance_logs_to_syslog',
        default=False,
        help="""
Forward the "vmware.log" files for all instances to the syslog monitoring
service. The syslog ID string is: [instance UUID] + '_vmx_log'.
"""),
]

vmwareapi_opts = [
    cfg.HostAddressOpt('host_ip',
                       help="""
Hostname or IP address for connection to VMware vCenter host."""),
    cfg.PortOpt('host_port',
                default=443,
                help="Port for connection to VMware vCenter host."),
    cfg.StrOpt('host_username',
               help="Username for connection to VMware vCenter host."),
    cfg.StrOpt('host_password',
               secret=True,
               help="Password for connection to VMware vCenter host."),
    cfg.StrOpt('ca_file',
               help="""
Specifies the CA bundle file to be used in verifying the vCenter
server certificate.
"""),
    cfg.BoolOpt('insecure',
                default=False,
                help="""
If true, the vCenter server certificate is not verified. If false,
then the default CA truststore is used for verification.

Related options:
* ca_file: This option is ignored if "ca_file" is set.
"""),
    cfg.StrOpt('cluster_name',
               help="Name of a VMware Cluster ComputeResource."),
    cfg.StrOpt('datastore_regex',
               help="""
Regular expression pattern to match the name of datastore.

The datastore_regex setting specifies the datastores to use with
Compute. For example, datastore_regex="nas.*" selects all the data
stores that have a name starting with "nas".

NOTE: If no regex is given, it just picks the datastore with the
most freespace.

Possible values:

* Any matching regular expression to a datastore must be given
"""),
    cfg.StrOpt('datastore_hagroup_regex',
                help="""
Regular expression pattern to retrieve ha-group from datastore name

If this setting is set, datastores are split into 2 ha-groups to distribute
anti-affin servers between them. The datastores found with the datastore_regex
setting belong to either HA-group A or B by applying this regex onto the
datastore name. This setting must include a matched group of the name
"hagroup". The regex defined here is used ignoring case.
"""),
    cfg.FloatOpt('task_poll_interval',
                 default=0.5,
                 help="""
Time interval in seconds to poll remote tasks invoked on
VMware VC server.
"""),
    cfg.IntOpt('api_retry_count',
               min=0,
               default=10,
               help="""
Number of times VMware vCenter server API must be retried on connection
failures, e.g. socket error, etc.
"""),
    cfg.PortOpt('vnc_port',
                default=5900,
                help="""
This option specifies VNC starting port.

Every VM created by ESX host has an option of enabling VNC client
for remote connection. Above option 'vnc_port' helps you to set
default starting port for the VNC client.

Possible values:

* Any valid port number within 5900 -(5900 + vnc_port_total)

Related options:
Below options should be set to enable VNC client.
* vnc.enabled = True
* vnc_port_total
"""),
    cfg.IntOpt('vnc_port_total',
               min=0,
               default=10000,
               help="""
Total number of VNC ports.
"""),
    cfg.StrOpt('vnc_keymap',
               default='en-us',
               help="""
Keymap for VNC.

The keyboard mapping (keymap) determines which keyboard layout a VNC
session should use by default.

Possible values:

* A keyboard layout which is supported by the underlying hypervisor on
  this node. This is usually an 'IETF language tag' (for example
  'en-us').
"""),
    cfg.BoolOpt('use_linked_clone',
                default=True,
                help="""
This option enables/disables the use of linked clone.

The ESX hypervisor requires a copy of the VMDK file in order to boot
up a virtual machine. The compute driver must download the VMDK via
HTTP from the OpenStack Image service to a datastore that is visible
to the hypervisor and cache it. Subsequent virtual machines that need
the VMDK use the cached version and don't have to copy the file again
from the OpenStack Image service.

If set to false, even with a cached VMDK, there is still a copy
operation from the cache location to the hypervisor file directory
in the shared datastore. If set to true, the above copy operation
is avoided as it creates copy of the virtual machine that shares
virtual disks with its parent VM.
"""),
    cfg.IntOpt('connection_pool_size',
               min=10,
               default=10,
               help="""
This option sets the http connection pool size

The connection pool size is the maximum number of connections from nova to
vSphere.  It should only be increased if there are warnings indicating that
the connection pool is full, otherwise, the default should suffice.
""")
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
"""),
    cfg.BoolOpt('full_clone_snapshots',
                default=False,
                help="""
Use full clones for creating image snapshots instead of linked clones.
With the right hardware support, it might be faster, especially on the export.
"""),
    cfg.BoolOpt('clone_from_snapshot',
                default=True,
                help="""
Create a snapshot of the VM before cloning it
"""),
    cfg.BoolOpt('image_as_template',
                default=False,
                help="""
Keep Glance images as VM templates in vCenter per datastore and create
instances as clone from template.
"""),
    cfg.BoolOpt('fetch_image_from_other_datastores',
                default=True,
                help="""
Before fetching from Glance an image missing on the datastore first look
for it on other datastores and clone it from there if available.
"""),
    cfg.BoolOpt('use_property_collector',
                default=True,
                help="""
Should the driver use a property collector to fetch essential properties
and keep a local copy of the values. This should reduce the load on the
vcenter api and be quicker, then polling each value individually
"""),
    cfg.IntOpt('min_disk_size_kb',
               default=1,
               help="""
The minimum size a disk is expected to have.
Some VASA providers need disks in the multiple MB range.
"""),
    cfg.StrOpt('smbios_asset_tag',
               help="""
Set the SMBIOS chassis asset tag to the specified value, so users can identify
the cloud-platform they're running on. E.g. Amazon sets this to "Amazon EC2".

Possible values:

* Any string or empty to keep VMware default
"""),
    cfg.StrOpt('bigvm_deployment_free_host_hostgroup_name',
        default='',
        help="""
Name of the hostgroup used to free up a host for special spawning.

All VMs in the cluster have to be in a VM group that has a rule specifying a
must-not-run-on-hostgroup rule for this hostgroup. Putting a host in this
hostgroup will then result in the host getting freed up by DRS.
"""),
    cfg.StrOpt('default_hw_version',
               default=None,
               help="""
Set a default hardware version for VMs, that can be overridden in flavors

This version is especially useful in multi-cluster environments where clusters
get upgraded individually but movement of VMs is necessary between them
nonetheless. It is recommend to set this to the highest version supported by
all clusters in the environment.

Example: "vmx-13" for vSphere 6.5.
Versions can be looked up here: https://kb.vmware.com/s/article/1003746
"""),
]

vmwareapi_driver_opts = [
    cfg.FloatOpt('server_group_sync_loop_max_group_spacing',
                 default=5,
                 min=0.5,
                 help="""
Amount of time in seconds between server-group sync via sync-loop

The sync-loop for server-groups in the driver iterates over all applicable
server-groups and calls "sync_server_group()" on them, sleeping a random time
before calling the sync. The amount of time slept at max can be defined by this
config value.

Possible values:
 * floating point value of seconds passed to random.uniform(0.5, X)
"""),
    cfg.IntOpt('server_group_sync_loop_spacing',
               default=3600,
               help="""
Amount of time in seconds to wait between server-group sync-loop runs

The sync-loop thread for server-groups runs continuously, sleeping after
syncing all groups. This setting defines how long to sleep between runs.

Possible values:
 * integer >= time in seconds to sleep between runs
 * intger < 0: disable the sync-loop
"""),
]

ALL_VMWARE_OPTS = (vmwareapi_vif_opts +
                  vmware_utils_opts +
                  vmwareapi_opts +
                  spbm_opts +
                  vmops_opts +
                  vmwareapi_driver_opts)


def register_opts(conf):
    conf.register_group(vmware_group)
    conf.register_opts(ALL_VMWARE_OPTS, group=vmware_group)


def list_opts():
    return {vmware_group: ALL_VMWARE_OPTS}
