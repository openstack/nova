# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2011 Piston Cloud Computing, Inc
# Copyright (c) 2012 University Of Minho
# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2015 Red Hat, Inc
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

"""
Manages information about the guest.

This class encapsulates libvirt domain provides certain
higher level APIs around the raw libvirt API. These APIs are
then used by all the other libvirt related classes
"""

import time
import typing as ty

from lxml import etree
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils

from nova.compute import power_state
from nova import exception
from nova.i18n import _
from nova.virt import hardware
from nova.virt.libvirt import config as vconfig


if ty.TYPE_CHECKING:
    import libvirt
else:
    libvirt = None

try:
    import libvirtmod_qemu
except ImportError:
    libvirtmod_qemu = None


LOG = logging.getLogger(__name__)

VIR_DOMAIN_NOSTATE = 0
VIR_DOMAIN_RUNNING = 1
VIR_DOMAIN_BLOCKED = 2
VIR_DOMAIN_PAUSED = 3
VIR_DOMAIN_SHUTDOWN = 4
VIR_DOMAIN_SHUTOFF = 5
VIR_DOMAIN_CRASHED = 6
VIR_DOMAIN_PMSUSPENDED = 7

LIBVIRT_POWER_STATE = {
    VIR_DOMAIN_NOSTATE: power_state.NOSTATE,
    VIR_DOMAIN_RUNNING: power_state.RUNNING,
    # The DOMAIN_BLOCKED state is only valid in Xen.  It means that
    # the VM is running and the vCPU is idle. So, we map it to RUNNING
    VIR_DOMAIN_BLOCKED: power_state.RUNNING,
    VIR_DOMAIN_PAUSED: power_state.PAUSED,
    # The libvirt API doc says that DOMAIN_SHUTDOWN means the domain
    # is being shut down. So technically the domain is still
    # running. SHUTOFF is the real powered off state.  But we will map
    # both to SHUTDOWN anyway.
    # http://libvirt.org/html/libvirt-libvirt.html
    VIR_DOMAIN_SHUTDOWN: power_state.SHUTDOWN,
    VIR_DOMAIN_SHUTOFF: power_state.SHUTDOWN,
    VIR_DOMAIN_CRASHED: power_state.CRASHED,
    VIR_DOMAIN_PMSUSPENDED: power_state.SUSPENDED,
}

# https://libvirt.org/html/libvirt-libvirt-domain.html#virDomainBlockJobType
VIR_DOMAIN_BLOCK_JOB_TYPE_UNKNOWN = 0
VIR_DOMAIN_BLOCK_JOB_TYPE_PULL = 1
VIR_DOMAIN_BLOCK_JOB_TYPE_COPY = 2
VIR_DOMAIN_BLOCK_JOB_TYPE_COMMIT = 3
VIR_DOMAIN_BLOCK_JOB_TYPE_ACTIVE_COMMIT = 4
VIR_DOMAIN_BLOCK_JOB_TYPE_BACKUP = 5
VIR_DOMAIN_BLOCK_JOB_TYPE_LAST = 6

LIBVIRT_BLOCK_JOB_TYPE = {
    VIR_DOMAIN_BLOCK_JOB_TYPE_UNKNOWN: 'UNKNOWN',
    VIR_DOMAIN_BLOCK_JOB_TYPE_PULL: 'PULL',
    VIR_DOMAIN_BLOCK_JOB_TYPE_COPY: 'COPY',
    VIR_DOMAIN_BLOCK_JOB_TYPE_COMMIT: 'COMMIT',
    VIR_DOMAIN_BLOCK_JOB_TYPE_ACTIVE_COMMIT: 'ACTIVE_COMMIT',
    VIR_DOMAIN_BLOCK_JOB_TYPE_BACKUP: 'BACKUP',
    VIR_DOMAIN_BLOCK_JOB_TYPE_LAST: 'LAST',
}


class Guest(object):

    def __init__(self, domain):

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')

        self._domain = domain

    def __repr__(self):
        return "<Guest %(id)d %(name)s %(uuid)s>" % {
            'id': self.id,
            'name': self.name,
            'uuid': self.uuid
        }

    @property
    def id(self):
        return self._domain.ID()

    @property
    def uuid(self):
        return self._domain.UUIDString()

    @property
    def name(self):
        return self._domain.name()

    @property
    def _encoded_xml(self):
        return encodeutils.safe_decode(self._domain.XMLDesc(0))

    @classmethod
    def create(cls, xml, host):
        """Create a new Guest

        :param xml: XML definition of the domain to create
        :param host: host.Host connection to define the guest on

        :returns guest.Guest: Guest ready to be launched
        """
        try:
            if isinstance(xml, bytes):
                xml = xml.decode('utf-8')
            guest = host.write_instance_config(xml)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error('Error defining a guest with XML: %s',
                          encodeutils.safe_decode(xml))
        return guest

    def launch(self, pause=False):
        """Starts a created guest.

        :param pause: Indicates whether to start and pause the guest
        """
        flags = pause and libvirt.VIR_DOMAIN_START_PAUSED or 0
        try:
            return self._domain.createWithFlags(flags)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception('Error launching a defined domain with XML: %s',
                              self._encoded_xml, errors='ignore')

    def poweroff(self):
        """Stops a running guest."""
        self._domain.destroy()

    def sync_guest_time(self):
        """Try to set VM time to the current value.  This is typically useful
        when clock wasn't running on the VM for some time (e.g. during
        suspension or migration), especially if the time delay exceeds NTP
        tolerance.

        It is not guaranteed that the time is actually set (it depends on guest
        environment, especially QEMU agent presence) or that the set time is
        very precise (NTP in the guest should take care of it if needed).
        """
        t = time.time()
        seconds = int(t)
        nseconds = int((t - seconds) * 10 ** 9)
        try:
            self._domain.setTime(time={'seconds': seconds,
                                       'nseconds': nseconds})
        except libvirt.libvirtError as e:
            code = e.get_error_code()
            if code == libvirt.VIR_ERR_AGENT_UNRESPONSIVE:
                LOG.debug('Failed to set time: QEMU agent unresponsive',
                          instance_uuid=self.uuid)
            elif code == libvirt.VIR_ERR_OPERATION_UNSUPPORTED:
                LOG.debug('Failed to set time: not supported',
                          instance_uuid=self.uuid)
            elif code == libvirt.VIR_ERR_ARGUMENT_UNSUPPORTED:
                LOG.debug('Failed to set time: agent not configured',
                          instance_uuid=self.uuid)
            else:
                LOG.warning('Failed to set time: %(reason)s',
                            {'reason': e}, instance_uuid=self.uuid)
        except Exception as ex:
            # The highest priority is not to let this method crash and thus
            # disrupt its caller in any way.  So we swallow this error here,
            # to be absolutely safe.
            LOG.debug('Failed to set time: %(reason)s',
                      {'reason': ex}, instance_uuid=self.uuid)
        else:
            LOG.debug('Time updated to: %d.%09d', seconds, nseconds,
                      instance_uuid=self.uuid)

    def inject_nmi(self):
        """Injects an NMI to a guest."""
        self._domain.injectNMI()

    def resume(self):
        """Resumes a paused guest."""
        self._domain.resume()

    def get_interfaces(self):
        """Returns a list of all network interfaces for this domain."""
        doc = None

        try:
            doc = etree.fromstring(self._encoded_xml)
        except Exception:
            return []

        interfaces = []

        nodes = doc.findall('./devices/interface/target')
        for target in nodes:
            interfaces.append(target.get('dev'))

        return interfaces

    def get_interface_by_cfg(
        self,
        cfg: vconfig.LibvirtConfigGuestDevice,
        from_persistent_config: bool = False
    ) -> ty.Optional[vconfig.LibvirtConfigGuestDevice]:
        """Lookup a full LibvirtConfigGuestDevice with
        LibvirtConfigGuesDevice generated
        by nova.virt.libvirt.vif.get_config.

        :param cfg: config object that represents the guest interface.
        :param from_persistent_config: query the device from the persistent
            domain instead of the live domain configuration
        :returns: nova.virt.libvirt.config.LibvirtConfigGuestDevice instance
            if found, else None
        """

        if cfg:
            LOG.debug(f'looking for interface given config: {cfg}')
            interfaces = self.get_all_devices(
                type(cfg), from_persistent_config)
            if not interfaces:
                LOG.debug(f'No interface of type: {type(cfg)} found in domain')
                return None
            # FIXME(sean-k-mooney): we should be able to print the list of
            # interfaces however some tests use incomplete objects that can't
            # be printed due to incomplete mocks or defects in the libvirt
            # fixture. Lets address this later.
            # LOG.debug(f'within interfaces: {list(interfaces)}')
            for interface in interfaces:
                # NOTE(leehom) LibvirtConfigGuest get from domain and
                # LibvirtConfigGuest generated by
                # nova.virt.libvirt.vif.get_config must be identical.
                # NOTE(gibi): LibvirtConfigGuest subtypes does a custom
                # equality check based on available information on nova side
                if cfg == interface:
                    return interface
            else:
                # NOTE(sean-k-mooney): {list(interfaces)} could be used
                # instead of self._domain.XMLDesc(0) once all tests have
                # printable interfaces see the comment above ^.
                # While the XML is more verbose it should always work
                # for our current test suite and in production code.
                LOG.debug(
                    f'interface for config: {cfg}'
                    f'not found in domain: {self._domain.XMLDesc(0)}'
                )
        return None

    def get_vcpus_info(self):
        """Returns virtual cpus information of guest.

        :returns: guest.VCPUInfo
        """
        vcpus = self._domain.vcpus()
        for vcpu in vcpus[0]:
            yield VCPUInfo(
                id=vcpu[0], cpu=vcpu[3], state=vcpu[1], time=vcpu[2])

    def delete_configuration(self):
        """Undefines a domain from hypervisor."""
        try:
            flags = libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE
            flags |= libvirt.VIR_DOMAIN_UNDEFINE_NVRAM
            self._domain.undefineFlags(flags)
        except libvirt.libvirtError:
            LOG.debug("Error from libvirt during undefineFlags for guest "
                      "%d. Retrying with undefine", self.id)
            self._domain.undefine()
        except AttributeError:
            # Older versions of libvirt don't support undefine flags,
            # trying to remove managed image
            try:
                if self._domain.hasManagedSaveImage(0):
                    self._domain.managedSaveRemove(0)
            except AttributeError:
                pass
            self._domain.undefine()

    def has_persistent_configuration(self):
        """Whether domain config is persistently stored on the host."""
        return self._domain.isPersistent()

    def attach_device(self, conf, persistent=False, live=False):
        """Attaches device to the guest.

        :param conf: A LibvirtConfigObject of the device to attach
        :param persistent: A bool to indicate whether the change is
                           persistent or not
        :param live: A bool to indicate whether it affect the guest
                     in running state
        """
        flags = persistent and libvirt.VIR_DOMAIN_AFFECT_CONFIG or 0
        flags |= live and libvirt.VIR_DOMAIN_AFFECT_LIVE or 0

        device_xml = conf.to_xml()
        if isinstance(device_xml, bytes):
            device_xml = device_xml.decode('utf-8')

        LOG.debug("attach device xml: %s", device_xml)
        self._domain.attachDeviceFlags(device_xml, flags=flags)

    def set_metadata(self, metadata, persistent=False, live=False):
        """Set metadata to the guest.

        Please note that this function completely replaces the existing
        metadata. The scope of the replacement is limited to the Nova-specific
        XML Namespace.

        :param metadata: A LibvirtConfigGuestMetaNovaInstance
        :param persistent: A bool to indicate whether the change is
                           persistent or not
        :param live: A bool to indicate whether it affect the guest
                     in running state
        """
        flags = persistent and libvirt.VIR_DOMAIN_AFFECT_CONFIG or 0
        flags |= live and libvirt.VIR_DOMAIN_AFFECT_LIVE or 0

        metadata_xml = metadata.to_xml()
        LOG.debug("set metadata xml: %s", metadata_xml)
        self._domain.setMetadata(libvirt.VIR_DOMAIN_METADATA_ELEMENT,
                                 metadata_xml, "instance",
                                 vconfig.NOVA_NS, flags=flags)

    def get_config(self):
        """Returns the config instance for a guest

        :returns: LibvirtConfigGuest instance
        """
        config = vconfig.LibvirtConfigGuest()
        config.parse_str(self._domain.XMLDesc(0))
        return config

    def get_disk(
        self,
        device: str,
        from_persistent_config: bool = False
    ) -> ty.Optional[vconfig.LibvirtConfigGuestDisk]:
        """Returns the disk mounted at device

        :param device: the name of either the source or the target device
        :param from_persistent_config: query the device from the persistent
            domain (i.e. inactive XML configuration that'll be used on next
            start of the domain) instead of the live domain configuration
        :returns LibvirtConfigGuestDisk: mounted at device or None
        """
        flags = 0
        if from_persistent_config:
            flags |= libvirt.VIR_DOMAIN_XML_INACTIVE
        try:
            doc = etree.fromstring(self._domain.XMLDesc(flags))
        except Exception:
            return None

        # FIXME(lyarwood): Workaround for the device being either a target dev
        # when called via swap_volume or source file when called via
        # live_snapshot. This should be removed once both are refactored to use
        # only the target dev of the device.
        node = doc.find("./devices/disk/target[@dev='%s'].." % device)
        if node is None:
            node = doc.find("./devices/disk/source[@file='%s'].." % device)

        if node is not None:
            conf = vconfig.LibvirtConfigGuestDisk()
            conf.parse_dom(node)
            return conf

        return None

    def get_all_disks(self):
        """Returns all the disks for a guest

        :returns: a list of LibvirtConfigGuestDisk instances
        """

        return self.get_all_devices(vconfig.LibvirtConfigGuestDisk)

    def get_device_by_alias(self, devalias, devtype=None,
                            from_persistent_config=False):
        for dev in self.get_all_devices(devtype):
            if hasattr(dev, 'alias') and dev.alias == devalias:
                return dev

    def get_all_devices(
        self,
        devtype: vconfig.LibvirtConfigGuestDevice = None,
        from_persistent_config: bool = False
    ) -> ty.List[vconfig.LibvirtConfigGuestDevice]:
        """Returns all devices for a guest

        :param devtype: a LibvirtConfigGuestDevice subclass class
        :param from_persistent_config: query the device from the persistent
            domain (i.e. inactive XML configuration that'll be used on next
            start of the domain) instead of the live domain configuration
        :returns: a list of LibvirtConfigGuestDevice instances
        """

        flags = 0
        if from_persistent_config:
            flags |= libvirt.VIR_DOMAIN_XML_INACTIVE

        try:
            config = vconfig.LibvirtConfigGuest()
            config.parse_str(
                self._domain.XMLDesc(flags))
        except Exception:
            return []

        devs = []
        for dev in config.devices:
            if (devtype is None or
                isinstance(dev, devtype)):
                devs.append(dev)
        return devs

    def detach_device(self, conf, persistent=False, live=False):
        """Detaches device to the guest.

        :param conf: A LibvirtConfigObject of the device to detach
        :param persistent: A bool to indicate whether the change is
                           persistent or not
        :param live: A bool to indicate whether it affect the guest
                     in running state
        """
        flags = persistent and libvirt.VIR_DOMAIN_AFFECT_CONFIG or 0
        flags |= live and libvirt.VIR_DOMAIN_AFFECT_LIVE or 0

        device_xml = conf.to_xml()
        if isinstance(device_xml, bytes):
            device_xml = device_xml.decode('utf-8')

        LOG.debug("detach device xml: %s", device_xml)
        self._domain.detachDeviceFlags(device_xml, flags=flags)

    def get_xml_desc(self, dump_inactive=False, dump_sensitive=False,
                     dump_migratable=False):
        """Returns xml description of guest.

        :param dump_inactive: Dump inactive domain information
        :param dump_sensitive: Dump security sensitive information
        :param dump_migratable: Dump XML suitable for migration

        :returns string: XML description of the guest
        """
        flags = dump_inactive and libvirt.VIR_DOMAIN_XML_INACTIVE or 0
        flags |= dump_sensitive and libvirt.VIR_DOMAIN_XML_SECURE or 0
        flags |= dump_migratable and libvirt.VIR_DOMAIN_XML_MIGRATABLE or 0
        return self._domain.XMLDesc(flags=flags)

    def save_memory_state(self):
        """Saves the domain's memory state. Requires running domain.

        raises: raises libvirtError on error
        """
        self._domain.managedSave(0)

    def get_block_device(self, disk):
        """Returns a block device wrapper for disk."""
        return BlockDevice(self, disk)

    def set_user_password(self, user, new_pass):
        """Configures a new user password."""
        self._domain.setUserPassword(user, new_pass, 0)

    def _get_domain_info(self):
        """Returns information on Guest.

        :returns list: [state, maxMem, memory, nrVirtCpu, cpuTime]
        """
        return self._domain.info()

    def get_info(self, host):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        :returns hardware.InstanceInfo:
        """
        try:
            dom_info = self._get_domain_info()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=self.uuid)

            msg = (_('Error from libvirt while getting domain info for '
                     '%(instance_name)s: [Error Code %(error_code)s] %(ex)s') %
                   {'instance_name': self.name,
                    'error_code': error_code,
                    'ex': ex})
            raise exception.InternalError(msg)

        return hardware.InstanceInfo(
            state=LIBVIRT_POWER_STATE[dom_info[0]],
            internal_id=self.id)

    def get_power_state(self, host):
        return self.get_info(host).state

    def is_active(self):
        "Determines whether guest is currently running."
        return self._domain.isActive()

    def freeze_filesystems(self):
        """Freeze filesystems within guest."""
        self._domain.fsFreeze()

    def thaw_filesystems(self):
        """Thaw filesystems within guest."""
        self._domain.fsThaw()

    def snapshot(self, conf, no_metadata=False,
                 disk_only=False, reuse_ext=False, quiesce=False):
        """Creates a guest snapshot.

        :param conf: libvirt.LibvirtConfigGuestSnapshotDisk
        :param no_metadata: Make snapshot without remembering it
        :param disk_only: Disk snapshot, no system checkpoint
        :param reuse_ext: Reuse any existing external files
        :param quiesce: Use QGA to quiesce all mounted file systems
        """
        flags = no_metadata and (
            libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA or 0)
        flags |= disk_only and (
            libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY or 0)
        flags |= reuse_ext and (
            libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT or 0)
        flags |= quiesce and libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE or 0

        device_xml = conf.to_xml()
        if isinstance(device_xml, bytes):
            device_xml = device_xml.decode('utf-8')

        self._domain.snapshotCreateXML(device_xml, flags=flags)

    def shutdown(self):
        """Shutdown guest"""
        self._domain.shutdown()

    def pause(self):
        """Suspends an active guest

        Process is frozen without further access to CPU resources and
        I/O but the memory used by the domain at the hypervisor level
        will stay allocated.

        See method "resume()" to reactive guest.
        """
        self._domain.suspend()

    def migrate(self, destination, migrate_uri=None, migrate_disks=None,
                destination_xml=None, flags=0, bandwidth=0):
        """Migrate guest object from its current host to the destination

        :param destination: URI of host destination where guest will be migrate
        :param migrate_uri: URI for invoking the migration
        :param migrate_disks: List of disks to be migrated
        :param destination_xml: The guest XML to be used on the target host
        :param flags: May be one of more of the following:
           VIR_MIGRATE_LIVE Do not pause the VM during migration
           VIR_MIGRATE_PEER2PEER Direct connection between source &
                                 destination hosts
           VIR_MIGRATE_TUNNELLED Tunnel migration data over the
                                 libvirt RPC channel
           VIR_MIGRATE_PERSIST_DEST If the migration is successful,
                                    persist the domain on the
                                    destination host.
           VIR_MIGRATE_UNDEFINE_SOURCE If the migration is successful,
                                       undefine the domain on the
                                       source host.
           VIR_MIGRATE_NON_SHARED_INC Migration with non-shared
                                      storage with incremental disk
                                      copy
           VIR_MIGRATE_AUTO_CONVERGE Slow down domain to make sure it does
                                     not change its memory faster than a
                                     hypervisor can transfer the changed
                                     memory to the destination host
           VIR_MIGRATE_POSTCOPY Tell libvirt to enable post-copy migration
           VIR_MIGRATE_TLS Use QEMU-native TLS
        :param bandwidth: The maximum bandwidth in MiB/s
        """
        params = {}
        # In migrateToURI3 these parameters are extracted from the
        # `params` dict
        params['bandwidth'] = bandwidth

        if destination_xml:
            params['destination_xml'] = destination_xml
            params['persistent_xml'] = destination_xml
        if migrate_disks:
            params['migrate_disks'] = migrate_disks
        if migrate_uri:
            params['migrate_uri'] = migrate_uri

        # Due to a quirk in the libvirt python bindings,
        # VIR_MIGRATE_NON_SHARED_INC with an empty migrate_disks is
        # interpreted as "block migrate all writable disks" rather than
        # "don't block migrate any disks". This includes attached
        # volumes, which will potentially corrupt data on those
        # volumes. Consequently we need to explicitly unset
        # VIR_MIGRATE_NON_SHARED_INC if there are no disks to be block
        # migrated.
        if (flags & libvirt.VIR_MIGRATE_NON_SHARED_INC != 0 and
                not params.get('migrate_disks')):
            flags &= ~libvirt.VIR_MIGRATE_NON_SHARED_INC

        self._domain.migrateToURI3(
            destination, params=params, flags=flags)

    def abort_job(self):
        """Requests to abort current background job"""
        self._domain.abortJob()

    def migrate_configure_max_downtime(self, mstime):
        """Sets maximum time for which domain is allowed to be paused

        :param mstime: Downtime in milliseconds.
        """
        self._domain.migrateSetMaxDowntime(mstime)

    def migrate_start_postcopy(self):
        """Switch running live migration to post-copy mode"""
        self._domain.migrateStartPostCopy()

    def announce_self(self):
        libvirtmod_qemu.virDomainQemuMonitorCommand(
            self._domain._o, 'announce_self', 1)

    def get_job_info(self):
        """Get job info for the domain

        Query the libvirt job info for the domain (ie progress
        of migration, or snapshot operation)

        :returns: a JobInfo of guest
        """
        if JobInfo._have_job_stats:
            try:
                stats = self._domain.jobStats()
                return JobInfo(**stats)
            except libvirt.libvirtError as ex:
                errmsg = ex.get_error_message()
                if ex.get_error_code() == libvirt.VIR_ERR_NO_SUPPORT:
                    # Remote libvirt doesn't support new API
                    LOG.debug("Missing remote virDomainGetJobStats: %s", ex)
                    JobInfo._have_job_stats = False
                    return JobInfo._get_job_stats_compat(self._domain)
                elif ex.get_error_code() in (
                        libvirt.VIR_ERR_NO_DOMAIN,
                        libvirt.VIR_ERR_OPERATION_INVALID):
                    # Transient guest finished migration, so it has gone
                    # away completclsely
                    LOG.debug("Domain has shutdown/gone away: %s", ex)
                    return JobInfo(type=libvirt.VIR_DOMAIN_JOB_COMPLETED)
                elif (ex.get_error_code() == libvirt.VIR_ERR_INTERNAL_ERROR and
                      errmsg and "migration was active, "
                      "but no RAM info was set" in errmsg):
                    LOG.debug("Migration is active or completed but "
                              "virDomainGetJobStats is missing ram: %s", ex)
                    return JobInfo(type=libvirt.VIR_DOMAIN_JOB_NONE)
                else:
                    LOG.debug("Failed to get job stats: %s", ex)
                    raise
            except AttributeError as ex:
                # Local python binding doesn't support new API
                LOG.debug("Missing local virDomainGetJobStats: %s", ex)
                JobInfo._have_job_stats = False
                return JobInfo._get_job_stats_compat(self._domain)
        else:
            return JobInfo._get_job_stats_compat(self._domain)


class BlockDevice(object):
    """Wrapper around block device API"""

    REBASE_DEFAULT_BANDWIDTH = 0  # in MiB/s - 0 unlimited
    COMMIT_DEFAULT_BANDWIDTH = 0  # in MiB/s - 0 unlimited

    def __init__(self, guest, disk):
        self._guest = guest
        self._disk = disk

    def abort_job(self, async_=False, pivot=False):
        """Request to cancel a live block device job

        :param async_: Cancel the block device job (e.g. 'copy' or
                       'commit'), and return as soon as possible, without
                       waiting for job completion
        :param pivot: Pivot to the destination image when ending a
                      'copy' or "active commit" (meaning: merging the
                      contents of current active disk into its backing
                      file) job
        """
        flags = async_ and libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_ASYNC or 0
        flags |= pivot and libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT or 0
        self._guest._domain.blockJobAbort(self._disk, flags=flags)

    def get_job_info(self):
        """Returns information about job currently running

        :returns: BlockDeviceJobInfo, or None if no job exists
        :raises: libvirt.libvirtError on error fetching block job info
        """

        # libvirt's blockJobInfo() raises libvirt.libvirtError if there was an
        # error. It returns {} if the job no longer exists, or a fully
        # populated dict if the job exists.
        status = self._guest._domain.blockJobInfo(self._disk, flags=0)

        # The job no longer exists
        if not status:
            return None

        return BlockDeviceJobInfo(
            job=status['type'],
            bandwidth=status['bandwidth'],
            cur=status['cur'],
            end=status['end'])

    def copy(self, dest_xml, shallow=False, reuse_ext=False, transient=False):
        """Copy the guest-visible contents into a new disk

        http://libvirt.org/html/libvirt-libvirt-domain.html#virDomainBlockCopy

        :param: dest_xml: XML describing the destination disk to copy to
        :param: shallow: Limit copy to top of source backing chain
        :param: reuse_ext: Reuse existing external file for a copy
        :param: transient: Don't force usage of recoverable job for the copy
                           operation
         """
        flags = shallow and libvirt.VIR_DOMAIN_BLOCK_COPY_SHALLOW or 0
        flags |= reuse_ext and libvirt.VIR_DOMAIN_BLOCK_COPY_REUSE_EXT or 0
        flags |= transient and libvirt.VIR_DOMAIN_BLOCK_COPY_TRANSIENT_JOB or 0
        return self._guest._domain.blockCopy(self._disk, dest_xml, flags=flags)

    def rebase(self, base, shallow=False, reuse_ext=False,
               copy=False, relative=False, copy_dev=False):
        """Copy data from backing chain into a new disk

        This copies data from backing file(s) into overlay(s), giving
        control over several aspects like what part of a disk image
        chain to be copied, whether to reuse an existing destination
        file, etc.  And updates the backing file to the new disk

        :param shallow: Limit copy to top of the source backing chain
        :param reuse_ext: Reuse an existing external file that was
                          pre-created
        :param copy: Start a copy job
        :param relative: Keep backing chain referenced using relative names
        :param copy_dev: Treat the destination as type="block"
        """
        flags = shallow and libvirt.VIR_DOMAIN_BLOCK_REBASE_SHALLOW or 0
        flags |= reuse_ext and libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT or 0
        flags |= copy and libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY or 0
        flags |= copy_dev and libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY_DEV or 0
        flags |= relative and libvirt.VIR_DOMAIN_BLOCK_REBASE_RELATIVE or 0
        return self._guest._domain.blockRebase(
            self._disk, base, self.REBASE_DEFAULT_BANDWIDTH, flags=flags)

    def commit(self, base, top, relative=False):
        """Merge data from overlays into backing file

        This live merges (or "commits") contents from backing files into
        overlays, thus reducing the length of a disk image chain.

        :param relative: Keep backing chain referenced using relative names
        """
        flags = relative and libvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE or 0
        return self._guest._domain.blockCommit(
            self._disk, base, top, self.COMMIT_DEFAULT_BANDWIDTH, flags=flags)

    def resize(self, size):
        """Resize block device to the given size in bytes.

        This resizes the block device within the instance to the given size.

        :param size: The size to resize the device to in bytes.
        """
        flags = libvirt.VIR_DOMAIN_BLOCK_RESIZE_BYTES
        self._guest._domain.blockResize(self._disk, size, flags=flags)

    def is_job_complete(self):
        """Return True if the job is complete, False otherwise

        :returns: True if the job is complete, False otherwise
        :raises: libvirt.libvirtError on error fetching block job info
        """
        # NOTE(mdbooth): This method polls for block job completion. It returns
        # true if either we get a status which indicates completion, or there
        # is no longer a record of the job. Ideally this method and its
        # callers would be rewritten to consume libvirt events from the job.
        # This would provide a couple of advantages. Firstly, as it would no
        # longer be polling it would notice completion immediately rather than
        # at the next 0.5s check, and would also consume fewer resources.
        # Secondly, with the current method we only know that 'no job'
        # indicates completion. It does not necessarily indicate successful
        # completion: the job could have failed, or been cancelled. When
        # polling for block job info we have no way to detect this, so we
        # assume success.

        status = self.get_job_info()

        # If the job no longer exists, it is because it has completed
        # NOTE(mdbooth): See comment above: it may not have succeeded.
        if status is None:
            return True

        # Track blockjob progress in DEBUG, helpful when reviewing failures.
        job_type = LIBVIRT_BLOCK_JOB_TYPE.get(
            status.job, f"Unknown to Nova ({status.job})")
        LOG.debug("%(job_type)s block job progress, current cursor: %(cur)s "
                  "final cursor: %(end)s",
                  {'job_type': job_type, 'cur': status.cur, 'end': status.end})

        # NOTE(lyarwood): Use the mirror element to determine if we can pivot
        # to the new disk once blockjobinfo reports progress as complete.
        if status.cur == status.end:
            disk = self._guest.get_disk(self._disk)
            if disk and disk.mirror:
                return disk.mirror.ready == 'yes'

        return False

    def blockStats(self):
        """Extracts block device statistics for a domain"""
        return self._guest._domain.blockStats(self._disk)


class VCPUInfo(object):
    def __init__(self, id, cpu, state, time):
        """Structure for information about guest vcpus.

        :param id: The virtual cpu number
        :param cpu: The host cpu currently associated
        :param state: The running state of the vcpu (0 offline, 1 running, 2
                      blocked on resource)
        :param time: The cpu time used in nanoseconds
        """
        self.id = id
        self.cpu = cpu
        self.state = state
        self.time = time


class BlockDeviceJobInfo(object):
    def __init__(self, job, bandwidth, cur, end):
        """Structure for information about running job.

        :param job: The running job (0 placeholder, 1 pull,
                      2 copy, 3 commit, 4 active commit)
        :param bandwidth: Used in MiB/s
        :param cur: Indicates the position between 0 and 'end'
        :param end: Indicates the position for this operation
        """
        self.job = job
        self.bandwidth = bandwidth
        self.cur = cur
        self.end = end


class JobInfo(object):
    """Information about libvirt background jobs

    This class encapsulates information about libvirt
    background jobs. It provides a mapping from either
    the old virDomainGetJobInfo API which returned a
    fixed list of fields, or the modern virDomainGetJobStats
    which returns an extendable dict of fields.
    """

    _have_job_stats = True

    def __init__(self, **kwargs):

        self.type = kwargs.get("type", libvirt.VIR_DOMAIN_JOB_NONE)
        self.time_elapsed = kwargs.get("time_elapsed", 0)
        self.time_remaining = kwargs.get("time_remaining", 0)
        self.downtime = kwargs.get("downtime", 0)
        self.setup_time = kwargs.get("setup_time", 0)
        self.data_total = kwargs.get("data_total", 0)
        self.data_processed = kwargs.get("data_processed", 0)
        self.data_remaining = kwargs.get("data_remaining", 0)
        self.memory_total = kwargs.get("memory_total", 0)
        self.memory_processed = kwargs.get("memory_processed", 0)
        self.memory_remaining = kwargs.get("memory_remaining", 0)
        self.memory_iteration = kwargs.get("memory_iteration", 0)
        self.memory_constant = kwargs.get("memory_constant", 0)
        self.memory_normal = kwargs.get("memory_normal", 0)
        self.memory_normal_bytes = kwargs.get("memory_normal_bytes", 0)
        self.memory_bps = kwargs.get("memory_bps", 0)
        self.disk_total = kwargs.get("disk_total", 0)
        self.disk_processed = kwargs.get("disk_processed", 0)
        self.disk_remaining = kwargs.get("disk_remaining", 0)
        self.disk_bps = kwargs.get("disk_bps", 0)
        self.comp_cache = kwargs.get("compression_cache", 0)
        self.comp_bytes = kwargs.get("compression_bytes", 0)
        self.comp_pages = kwargs.get("compression_pages", 0)
        self.comp_cache_misses = kwargs.get("compression_cache_misses", 0)
        self.comp_overflow = kwargs.get("compression_overflow", 0)

    @classmethod
    def _get_job_stats_compat(cls, dom):
        # Make the old virDomainGetJobInfo method look similar to the
        # modern virDomainGetJobStats method
        try:
            info = dom.jobInfo()
        except libvirt.libvirtError as ex:
            # When migration of a transient guest completes, the guest
            # goes away so we'll see NO_DOMAIN error code
            #
            # When migration of a persistent guest completes, the guest
            # merely shuts off, but libvirt unhelpfully raises an
            # OPERATION_INVALID error code
            #
            # Lets pretend both of these mean success
            if ex.get_error_code() in (libvirt.VIR_ERR_NO_DOMAIN,
                                       libvirt.VIR_ERR_OPERATION_INVALID):
                LOG.debug("Domain has shutdown/gone away: %s", ex)
                return cls(type=libvirt.VIR_DOMAIN_JOB_COMPLETED)
            else:
                LOG.debug("Failed to get job info: %s", ex)
                raise

        return cls(
            type=info[0],
            time_elapsed=info[1],
            time_remaining=info[2],
            data_total=info[3],
            data_processed=info[4],
            data_remaining=info[5],
            memory_total=info[6],
            memory_processed=info[7],
            memory_remaining=info[8],
            disk_total=info[9],
            disk_processed=info[10],
            disk_remaining=info[11])
