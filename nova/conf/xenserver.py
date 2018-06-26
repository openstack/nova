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
from oslo_utils import units

xenserver_group = cfg.OptGroup('xenserver',
                               title='Xenserver Options',
                               help="""
XenServer options are used when the compute_driver is set to use
XenServer (compute_driver=xenapi.XenAPIDriver).

Must specify connection_url, connection_password and ovs_integration_bridge to
use compute_driver=xenapi.XenAPIDriver.
""")

xenapi_agent_opts = [
    cfg.IntOpt('agent_timeout',
        default=30,
        min=0,
        help="""
Number of seconds to wait for agent's reply to a request.

Nova configures/performs certain administrative actions on a server with the
help of an agent that's installed on the server. The communication between
Nova and the agent is achieved via sharing messages, called records, over
xenstore, a shared storage across all the domains on a Xenserver host.
Operations performed by the agent on behalf of nova are: 'version',' key_init',
'password','resetnetwork','inject_file', and 'agentupdate'.

To perform one of the above operations, the xapi 'agent' plugin writes the
command and its associated parameters to a certain location known to the domain
and awaits response. On being notified of the message, the agent performs
appropriate actions on the server and writes the result back to xenstore. This
result is then read by the xapi 'agent' plugin to determine the success/failure
of the operation.

This config option determines how long the xapi 'agent' plugin shall wait to
read the response off of xenstore for a given request/command. If the agent on
the instance fails to write the result in this time period, the operation is
considered to have timed out.

Related options:

* ``agent_version_timeout``
* ``agent_resetnetwork_timeout``

"""),
    cfg.IntOpt('agent_version_timeout',
        default=300,
        min=0,
        help="""
Number of seconds to wait for agent't reply to version request.

This indicates the amount of time xapi 'agent' plugin waits for the agent to
respond to the 'version' request specifically. The generic timeout for agent
communication ``agent_timeout`` is ignored in this case.

During the build process the 'version' request is used to determine if the
agent is available/operational to perform other requests such as
'resetnetwork', 'password', 'key_init' and 'inject_file'. If the 'version' call
fails, the other configuration is skipped. So, this configuration option can
also be interpreted as time in which agent is expected to be fully operational.
"""),
    cfg.IntOpt('agent_resetnetwork_timeout',
        default=60,
        min=0,
        help="""
Number of seconds to wait for agent's reply to resetnetwork
request.

This indicates the amount of time xapi 'agent' plugin waits for the agent to
respond to the 'resetnetwork' request specifically. The generic timeout for
agent communication ``agent_timeout`` is ignored in this case.
"""),
    cfg.StrOpt('agent_path',
        default='usr/sbin/xe-update-networking',
        help="""
Path to locate guest agent on the server.

Specifies the path in which the XenAPI guest agent should be located. If the
agent is present, network configuration is not injected into the image.

Related options:

For this option to have an effect:
* ``flat_injected`` should be set to ``True``
* ``compute_driver`` should be set to ``xenapi.XenAPIDriver``

"""),
    cfg.BoolOpt('disable_agent',
        default=False,
        help="""
Disables the use of XenAPI agent.

This configuration option suggests whether the use of agent should be enabled
or not regardless of what image properties are present. Image properties have
an effect only when this is set to ``True``. Read description of config option
``use_agent_default`` for more information.

Related options:

* ``use_agent_default``

"""),
    cfg.BoolOpt('use_agent_default',
        default=False,
        help="""
Whether or not to use the agent by default when its usage is enabled but not
indicated by the image.

The use of XenAPI agent can be disabled altogether using the configuration
option ``disable_agent``. However, if it is not disabled, the use of an agent
can still be controlled by the image in use through one of its properties,
``xenapi_use_agent``. If this property is either not present or specified
incorrectly on the image, the use of agent is determined by this configuration
option.

Note that if this configuration is set to ``True`` when the agent is not
present, the boot times will increase significantly.

Related options:

* ``disable_agent``

"""),
]


xenapi_session_opts = [
    cfg.IntOpt('login_timeout',
        default=10,
        min=0,
        help='Timeout in seconds for XenAPI login.'),
    cfg.IntOpt('connection_concurrent',
        default=5,
        min=1,
        help="""
Maximum number of concurrent XenAPI connections.

In nova, multiple XenAPI requests can happen at a time.
Configuring this option will parallelize access to the XenAPI
session, which allows you to make concurrent XenAPI connections.
"""),
]


xenapi_vm_utils_opts = [
    cfg.StrOpt('cache_images',
        default='all',
        choices=('all', 'some', 'none'),
        help="""
Cache glance images locally.

The value for this option must be chosen from the choices listed
here. Configuring a value other than these will default to 'all'.

Note: There is nothing that deletes these images.

Possible values:

* `all`: will cache all images.
* `some`: will only cache images that have the
  image_property `cache_in_nova=True`.
* `none`: turns off caching entirely.
"""),
    cfg.IntOpt('image_compression_level',
        min=1,
        max=9,
        help="""
Compression level for images.

By setting this option we can configure the gzip compression level.
This option sets GZIP environment variable before spawning tar -cz
to force the compression level. It defaults to none, which means the
GZIP environment variable is not set and the default (usually -6)
is used.

Possible values:

* Range is 1-9, e.g., 9 for gzip -9, 9 being most
  compressed but most CPU intensive on dom0.
* Any values out of this range will default to None.
"""),
    cfg.StrOpt('default_os_type',
        default='linux',
        help='Default OS type used when uploading an image to glance'),
    cfg.IntOpt('block_device_creation_timeout',
        default=10,
        min=1,
        help='Time in secs to wait for a block device to be created'),
    cfg.IntOpt('max_kernel_ramdisk_size',
        default=16 * units.Mi,
        help="""
Maximum size in bytes of kernel or ramdisk images.

Specifying the maximum size of kernel or ramdisk will avoid copying
large files to dom0 and fill up /boot/guest.
"""),
    cfg.StrOpt('sr_matching_filter',
        default='default-sr:true',
        help="""
Filter for finding the SR to be used to install guest instances on.

Possible values:

* To use the Local Storage in default XenServer/XCP installations
  set this flag to other-config:i18n-key=local-storage.
* To select an SR with a different matching criteria, you could
  set it to other-config:my_favorite_sr=true.
* To fall back on the Default SR, as displayed by XenCenter,
  set this flag to: default-sr:true.
"""),
    cfg.BoolOpt('sparse_copy',
        default=True,
        help="""
Whether to use sparse_copy for copying data on a resize down.
(False will use standard dd). This speeds up resizes down
considerably since large runs of zeros won't have to be rsynced.
"""),
    cfg.IntOpt('num_vbd_unplug_retries',
        default=10,
        min=0,
        help="""
Maximum number of retries to unplug VBD.
If set to 0, should try once, no retries.
"""),
    cfg.StrOpt('ipxe_network_name',
        help="""
Name of network to use for booting iPXE ISOs.

An iPXE ISO is a specially crafted ISO which supports iPXE booting.
This feature gives a means to roll your own image.

By default this option is not set. Enable this option to
boot an iPXE ISO.

Related Options:

* `ipxe_boot_menu_url`
* `ipxe_mkisofs_cmd`
"""),
    cfg.StrOpt('ipxe_boot_menu_url',
        help="""
URL to the iPXE boot menu.

An iPXE ISO is a specially crafted ISO which supports iPXE booting.
This feature gives a means to roll your own image.

By default this option is not set. Enable this option to
boot an iPXE ISO.

Related Options:

* `ipxe_network_name`
* `ipxe_mkisofs_cmd`
"""),
    cfg.StrOpt('ipxe_mkisofs_cmd',
        default='mkisofs',
        help="""
Name and optionally path of the tool used for ISO image creation.

An iPXE ISO is a specially crafted ISO which supports iPXE booting.
This feature gives a means to roll your own image.

Note: By default `mkisofs` is not present in the Dom0, so the
package can either be manually added to Dom0 or include the
`mkisofs` binary in the image itself.

Related Options:

* `ipxe_network_name`
* `ipxe_boot_menu_url`
"""),
]


xenapi_opts = [
    cfg.StrOpt('connection_url',
        help="""
URL for connection to XenServer/Xen Cloud Platform. A special value
of unix://local can be used to connect to the local unix socket.

Possible values:

* Any string that represents a URL. The connection_url is
  generally the management network IP address of the XenServer.
* This option must be set if you chose the XenServer driver.
"""),
    cfg.StrOpt('connection_username',
        default='root',
        help='Username for connection to XenServer/Xen Cloud Platform'),
    cfg.StrOpt('connection_password',
        secret=True,
        help='Password for connection to XenServer/Xen Cloud Platform'),
    cfg.FloatOpt('vhd_coalesce_poll_interval',
        default=5.0,
        min=0,
        help="""
The interval used for polling of coalescing vhds.

This is the interval after which the task of coalesce VHD is
performed, until it reaches the max attempts that is set by
vhd_coalesce_max_attempts.

Related options:

* `vhd_coalesce_max_attempts`
"""),
    cfg.BoolOpt('check_host',
        default=True,
        help="""
Ensure compute service is running on host XenAPI connects to.
This option must be set to false if the 'independent_compute'
option is set to true.

Possible values:

* Setting this option to true will make sure that compute service
  is running on the same host that is specified by connection_url.
* Setting this option to false, doesn't perform the check.

Related options:

* `independent_compute`
"""),
    cfg.IntOpt('vhd_coalesce_max_attempts',
        default=20,
        min=0,
        help="""
Max number of times to poll for VHD to coalesce.

This option determines the maximum number of attempts that can be
made for coalescing the VHD before giving up.

Related opitons:

* `vhd_coalesce_poll_interval`
"""),
    cfg.StrOpt('sr_base_path',
        default='/var/run/sr-mount',
        help='Base path to the storage repository on the XenServer host.'),
    cfg.HostAddressOpt('target_host',
        help="""
The iSCSI Target Host.

This option represents the hostname or ip of the iSCSI Target.
If the target host is not present in the connection information from
the volume provider then the value from this option is taken.

Possible values:

* Any string that represents hostname/ip of Target.
"""),
    cfg.PortOpt('target_port',
        default=3260,
        help="""
The iSCSI Target Port.

This option represents the port of the iSCSI Target. If the
target port is not present in the connection information from the
volume provider then the value from this option is taken.
"""),
    cfg.BoolOpt('independent_compute',
        default=False,
        help="""
Used to prevent attempts to attach VBDs locally, so Nova can
be run in a VM on a different host.

Related options:

* ``CONF.flat_injected`` (Must be False)
* ``CONF.xenserver.check_host`` (Must be False)
* ``CONF.default_ephemeral_format`` (Must be unset or 'ext3')
* Joining host aggregates (will error if attempted)
* Swap disks for Windows VMs (will error if attempted)
* Nova-based auto_configure_disk (will error if attempted)
""")
]

xenapi_vmops_opts = [
    cfg.IntOpt('running_timeout',
        default=60,
        min=0,
        help="""
Wait time for instances to go to running state.

Provide an integer value representing time in seconds to set the
wait time for an instance to go to running state.

When a request to create an instance is received by nova-api and
communicated to nova-compute, the creation of the instance occurs
through interaction with Xen via XenAPI in the compute node. Once
the node on which the instance(s) are to be launched is decided by
nova-schedule and the launch is triggered, a certain amount of wait
time is involved until the instance(s) can become available and
'running'. This wait time is defined by running_timeout. If the
instances do not go to running state within this specified wait
time, the launch expires and the instance(s) are set to 'error'
state.
"""),
    # TODO(dharinic): Make this, a stevedore plugin
    cfg.StrOpt('image_upload_handler',
        default='',
        deprecated_for_removal=True,
        deprecated_since='18.0.0',
        deprecated_reason="""
Instead of setting the class path here, we will use short names
to represent image handlers. The download and upload handlers
must also be matching. So another new option "image_handler"
will be used to set the short name for a specific image handler
for both image download and upload.
""",
        help="""
Dom0 plugin driver used to handle image uploads.

Provide a string value representing a plugin driver required to
handle the image uploading to GlanceStore.

Images, and snapshots from XenServer need to be uploaded to the data
store for use. image_upload_handler takes in a value for the Dom0
plugin driver. This driver is then called to uplaod images to the
GlanceStore.
"""),
    cfg.StrOpt('image_handler',
        default='direct_vhd',
        choices=('direct_vhd', 'vdi_local_dev', 'vdi_remote_stream'),
        help="""
The plugin used to handle image uploads and downloads.

Provide a short name representing an image driver required to
handle the image between compute host and glance.

Description for the allowed values:
* ``direct_vhd``: This plugin directly processes the VHD files in XenServer
SR(Storage Repository). So this plugin only works when the host's SR
type is file system based e.g. ext, nfs.
* ``vdi_local_dev``: This plugin implements an image handler which attaches
the instance's VDI as a local disk to the VM where the OpenStack Compute
service runs in. It uploads the raw disk to glance when creating image;
When booting an instance from a glance image, it downloads the image and
streams it into the disk which is attached to the compute VM.
* ``vdi_remote_stream``: This plugin implements an image handler which works
as a proxy between glance and XenServer. The VHD streams to XenServer via
a remote import API supplied by XAPI for image download; and for image
upload, the VHD streams from XenServer via a remote export API supplied
by XAPI. This plugin works for all SR types supported by XenServer.
"""),
]

xenapi_volume_utils_opts = [
    cfg.IntOpt('introduce_vdi_retry_wait',
        default=20,
        min=0,
        help="""
Number of seconds to wait for SR to settle if the VDI
does not exist when first introduced.

Some SRs, particularly iSCSI connections are slow to see the VDIs
right after they got introduced. Setting this option to a
time interval will make the SR to wait for that time period
before raising VDI not found exception.
""")
]

xenapi_ovs_integration_bridge_opts = [
    cfg.StrOpt('ovs_integration_bridge',
        help="""
The name of the integration Bridge that is used with xenapi
when connecting with Open vSwitch.

Note: The value of this config option is dependent on the
environment, therefore this configuration value must be set
accordingly if you are using XenAPI.

Possible values:

* Any string that represents a bridge name.
"""),
]

xenapi_pool_opts = [
    # TODO(macsz): This should be deprecated. Until providing solid reason,
    # leaving it as-it-is.
    cfg.BoolOpt('use_join_force',
        default=True,
        help="""
When adding new host to a pool, this will append a --force flag to the
command, forcing hosts to join a pool, even if they have different CPUs.

Since XenServer version 5.6 it is possible to create a pool of hosts that have
different CPU capabilities. To accommodate CPU differences, XenServer limited
features it uses to determine CPU compatibility to only the ones that are
exposed by CPU and support for CPU masking was added.
Despite this effort to level differences between CPUs, it is still possible
that adding new host will fail, thus option to force join was introduced.
"""),
]

xenapi_console_opts = [
    cfg.StrOpt('console_public_hostname',
        default=socket.gethostname(),
        sample_default='<current_hostname>',
        deprecated_group='DEFAULT',
        help="""
Publicly visible name for this console host.

Possible values:

* Current hostname (default) or any string representing hostname.
"""),
]

ALL_XENSERVER_OPTS = (xenapi_agent_opts +
                      xenapi_session_opts +
                      xenapi_vm_utils_opts +
                      xenapi_opts +
                      xenapi_vmops_opts +
                      xenapi_volume_utils_opts +
                      xenapi_ovs_integration_bridge_opts +
                      xenapi_pool_opts +
                      xenapi_console_opts)


def register_opts(conf):
    conf.register_group(xenserver_group)
    conf.register_opts(ALL_XENSERVER_OPTS, group=xenserver_group)


def list_opts():
    return {xenserver_group: ALL_XENSERVER_OPTS}
