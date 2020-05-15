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

"""The 'workarounds' group is for very specific reasons.

If you're:

 - Working around an issue in a system tool (e.g. libvirt or qemu) where the
   fix is in flight/discussed in that community.
 - The tool can be/is fixed in some distributions and rather than patch the
   code those distributions can trivially set a config option to get the
   "correct" behavior.

Then this is a good place for your workaround.

.. warning::

  Please use with care! Document the BugID that your workaround is paired with.
"""

from oslo_config import cfg

workarounds_group = cfg.OptGroup(
    'workarounds',
    title='Workaround Options',
    help="""
A collection of workarounds used to mitigate bugs or issues found in system
tools (e.g. Libvirt or QEMU) or Nova itself under certain conditions. These
should only be enabled in exceptional circumstances. All options are linked
against bug IDs, where more information on the issue can be found.
""")
ALL_OPTS = [
    cfg.BoolOpt(
        'disable_rootwrap',
        default=False,
        help="""
Use sudo instead of rootwrap.

Allow fallback to sudo for performance reasons.

For more information, refer to the bug report:

  https://bugs.launchpad.net/nova/+bug/1415106

Possible values:

* True: Use sudo instead of rootwrap
* False: Use rootwrap as usual

Interdependencies to other options:

* Any options that affect 'rootwrap' will be ignored.
"""),

    cfg.BoolOpt(
        'disable_libvirt_livesnapshot',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='19.0.0',
        deprecated_reason="""
This option was added to work around issues with libvirt 1.2.2. We no longer
support this version of libvirt, which means this workaround is no longer
necessary. It will be removed in a future release.
""",
        help="""
Disable live snapshots when using the libvirt driver.

Live snapshots allow the snapshot of the disk to happen without an
interruption to the guest, using coordination with a guest agent to
quiesce the filesystem.

When using libvirt 1.2.2 live snapshots fail intermittently under load
(likely related to concurrent libvirt/qemu operations). This config
option provides a mechanism to disable live snapshot, in favor of cold
snapshot, while this is resolved. Cold snapshot causes an instance
outage while the guest is going through the snapshotting process.

For more information, refer to the bug report:

  https://bugs.launchpad.net/nova/+bug/1334398

Possible values:

* True: Live snapshot is disabled when using libvirt
* False: Live snapshots are always used when snapshotting (as long as
  there is a new enough libvirt and the backend storage supports it)
"""),

    cfg.BoolOpt(
        'handle_virt_lifecycle_events',
        default=True,
        help="""
Enable handling of events emitted from compute drivers.

Many compute drivers emit lifecycle events, which are events that occur when,
for example, an instance is starting or stopping. If the instance is going
through task state changes due to an API operation, like resize, the events
are ignored.

This is an advanced feature which allows the hypervisor to signal to the
compute service that an unexpected state change has occurred in an instance
and that the instance can be shutdown automatically. Unfortunately, this can
race in some conditions, for example in reboot operations or when the compute
service or when host is rebooted (planned or due to an outage). If such races
are common, then it is advisable to disable this feature.

Care should be taken when this feature is disabled and
'sync_power_state_interval' is set to a negative value. In this case, any
instances that get out of sync between the hypervisor and the Nova database
will have to be synchronized manually.

For more information, refer to the bug report:
https://bugs.launchpad.net/bugs/1444630

Interdependencies to other options:

* If ``sync_power_state_interval`` is negative and this feature is disabled,
  then instances that get out of sync between the hypervisor and the Nova
  database will have to be synchronized manually.
"""),

    cfg.BoolOpt(
        'disable_group_policy_check_upcall',
        default=False,
        help="""
Disable the server group policy check upcall in compute.

In order to detect races with server group affinity policy, the compute
service attempts to validate that the policy was not violated by the
scheduler. It does this by making an upcall to the API database to list
the instances in the server group for one that it is booting, which violates
our api/cell isolation goals. Eventually this will be solved by proper affinity
guarantees in the scheduler and placement service, but until then, this late
check is needed to ensure proper affinity policy.

Operators that desire api/cell isolation over this check should
enable this flag, which will avoid making that upcall from compute.

Related options:

* [filter_scheduler]/track_instance_changes also relies on upcalls from the
  compute service to the scheduler service.
"""),

    cfg.BoolOpt(
        'enable_numa_live_migration',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='20.0.0',
        deprecated_reason="""This option was added to mitigate known issues
when live migrating instances with a NUMA topology with the libvirt driver.
Those issues are resolved in Train. Clouds using the libvirt driver and fully
upgraded to Train support NUMA-aware live migration. This option will be
removed in a future release.
""",
        help="""
Enable live migration of instances with NUMA topologies.

Live migration of instances with NUMA topologies when using the libvirt driver
is only supported in deployments that have been fully upgraded to Train. In
previous versions, or in mixed Stein/Train deployments with a rolling upgrade
in progress, live migration of instances with NUMA topologies is disabled by
default when using the libvirt driver. This includes live migration of
instances with CPU pinning or hugepages. CPU pinning and huge page information
for such instances is not currently re-calculated, as noted in `bug #1289064`_.
This means that if instances were already present on the destination host, the
migrated instance could be placed on the same dedicated cores as these
instances or use hugepages allocated for another instance. Alternately, if the
host platforms were not homogeneous, the instance could be assigned to
non-existent cores or be inadvertently split across host NUMA nodes.

Despite these known issues, there may be cases where live migration is
necessary. By enabling this option, operators that are aware of the issues and
are willing to manually work around them can enable live migration support for
these instances.

Related options:

* ``compute_driver``: Only the libvirt driver is affected.

.. _bug #1289064: https://bugs.launchpad.net/nova/+bug/1289064
"""),

    cfg.BoolOpt(
        'ensure_libvirt_rbd_instance_dir_cleanup',
        default=False,
        help="""
Ensure the instance directory is removed during clean up when using rbd.

When enabled this workaround will ensure that the instance directory is always
removed during cleanup on hosts using ``[libvirt]/images_type=rbd``. This
avoids the following bugs with evacuation and revert resize clean up that lead
to the instance directory remaining on the host:

https://bugs.launchpad.net/nova/+bug/1414895

https://bugs.launchpad.net/nova/+bug/1761062

Both of these bugs can then result in ``DestinationDiskExists`` errors being
raised if the instances ever attempt to return to the host.

.. warning:: Operators will need to ensure that the instance directory itself,
  specified by ``[DEFAULT]/instances_path``, is not shared between computes
  before enabling this workaround otherwise the console.log, kernels, ramdisks
  and any additional files being used by the running instance will be lost.

Related options:

* ``compute_driver`` (libvirt)
* ``[libvirt]/images_type`` (rbd)
* ``instances_path``
"""),

    cfg.BoolOpt(
        'disable_fallback_pcpu_query',
        default=False,
        deprecated_for_removal=True,
        deprecated_since='20.0.0',
        help="""
Disable fallback request for VCPU allocations when using pinned instances.

Starting in Train, compute nodes using the libvirt virt driver can report
``PCPU`` inventory and will use this for pinned instances. The scheduler will
automatically translate requests using the legacy CPU pinning-related flavor
extra specs, ``hw:cpu_policy`` and ``hw:cpu_thread_policy``, their image
metadata property equivalents, and the emulator threads pinning flavor extra
spec, ``hw:emulator_threads_policy``, to new placement requests. However,
compute nodes require additional configuration in order to report ``PCPU``
inventory and this configuration may not be present immediately after an
upgrade. To ensure pinned instances can be created without this additional
configuration, the scheduler will make a second request to placement for
old-style ``VCPU``-based allocations and fallback to these allocation
candidates if necessary. This has a slight performance impact and is not
necessary on new or upgraded deployments where the new configuration has been
set on all hosts. By setting this option, the second lookup is disabled and the
scheduler will only request ``PCPU``-based allocations.
"""),
    cfg.BoolOpt('reserve_disk_resource_for_image_cache',
               default=False,
               help="""
If it is set to True then the libvirt driver will reserve DISK_GB resource for
the images stored in the image cache. If the
:oslo.config:option:`DEFAULT.instances_path` is on different disk partition
than the image cache directory then the driver will not reserve resource for
the cache.

Such disk reservation is done by a periodic task in the resource tracker that
runs every :oslo.config:option:`update_resources_interval` seconds. So the
reservation is not updated immediately when an image is cached.

Related options:

* :oslo.config:option:`DEFAULT.instances_path`
* :oslo.config:option:`image_cache_subdirectory_name`
* :oslo.config:option:`update_resources_interval`
"""),
]


def register_opts(conf):
    conf.register_group(workarounds_group)
    conf.register_opts(ALL_OPTS, group=workarounds_group)


def list_opts():
    return {workarounds_group: ALL_OPTS}
