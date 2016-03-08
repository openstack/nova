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

from lxml import etree
from oslo_log import log as logging
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils

from nova.compute import power_state
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova import utils
from nova.virt import hardware
from nova.virt.libvirt import compat
from nova.virt.libvirt import config as vconfig

libvirt = None

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
            # TODO(sahid): Host.write_instance_config should return
            # an instance of Guest
            domain = host.write_instance_config(xml)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error defining a domain with XML: %s'),
                          encodeutils.safe_decode(xml))
        return cls(domain)

    def launch(self, pause=False):
        """Starts a created guest.

        :param pause: Indicates whether to start and pause the guest
        """
        flags = pause and libvirt.VIR_DOMAIN_START_PAUSED or 0
        try:
            return self._domain.createWithFlags(flags)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error launching a defined domain '
                              'with XML: %s'),
                          self._encoded_xml, errors='ignore')

    def poweroff(self):
        """Stops a running guest."""
        self._domain.destroy()

    def inject_nmi(self):
        """Injects an NMI to a guest."""
        self._domain.injectNMI()

    def resume(self):
        """Resumes a suspended guest."""
        self._domain.resume()

    def enable_hairpin(self):
        """Enables hairpin mode for this guest."""
        interfaces = self.get_interfaces()
        try:
            for interface in interfaces:
                utils.execute(
                    'tee',
                    '/sys/class/net/%s/brport/hairpin_mode' % interface,
                    process_input='1',
                    run_as_root=True,
                    check_exit_code=[0, 1])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error enabling hairpin mode with XML: %s'),
                          self._encoded_xml, errors='ignore')

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

    def get_interface_by_mac(self, mac):
        """Lookup a LibvirtConfigGuestInterface by the MAC address.

        :param mac: MAC address of the guest interface.
        :type mac: str
        :returns: nova.virt.libvirt.config.LibvirtConfigGuestInterface instance
            if found, else None
        """

        if mac:
            interfaces = self.get_all_devices(
                vconfig.LibvirtConfigGuestInterface)
            for interface in interfaces:
                if interface.mac_addr == mac:
                    return interface

    def get_vcpus_info(self):
        """Returns virtual cpus information of guest.

        :returns: guest.VCPUInfo
        """
        vcpus = self._domain.vcpus()
        if vcpus is not None:
            for vcpu in vcpus[0]:
                yield VCPUInfo(
                    id=vcpu[0], cpu=vcpu[3], state=vcpu[1], time=vcpu[2])

    def delete_configuration(self):
        """Undefines a domain from hypervisor."""
        try:
            self._domain.undefineFlags(
                libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
        except libvirt.libvirtError:
            LOG.debug("Error from libvirt during undefineFlags. %d"
                      "Retrying with undefine", self.id)
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
        self._domain.attachDeviceFlags(conf.to_xml(), flags=flags)

    def get_disk(self, device):
        """Returns the disk mounted at device

        :returns LivirtConfigGuestDisk: mounted at device or None
        """
        try:
            doc = etree.fromstring(self._domain.XMLDesc(0))
        except Exception:
            return None
        node = doc.find("./devices/disk/target[@dev='%s'].." % device)
        if node is not None:
            conf = vconfig.LibvirtConfigGuestDisk()
            conf.parse_dom(node)
            return conf

    def get_all_disks(self):
        """Returns all the disks for a guest

        :returns: a list of LibvirtConfigGuestDisk instances
        """

        return self.get_all_devices(vconfig.LibvirtConfigGuestDisk)

    def get_all_devices(self, devtype=None):
        """Returns all devices for a guest

        :param devtype: a LibvirtConfigGuestDevice subclass class

        :returns: a list of LibvirtConfigGuestDevice instances
        """

        try:
            config = vconfig.LibvirtConfigGuest()
            config.parse_str(
                self._domain.XMLDesc(0))
        except Exception:
            return []

        devs = []
        for dev in config.devices:
            if (devtype is None or
                isinstance(dev, devtype)):
                devs.append(dev)
        return devs

    def detach_device_with_retry(self, get_device_conf_func, device,
                                 persistent, live, max_retry_count=7,
                                 inc_sleep_time=2,
                                 max_sleep_time=30):
        """Detaches a device from the guest. After the initial detach request,
        a function is returned which can be used to ensure the device is
        successfully removed from the guest domain (retrying the removal as
        necessary).

        :param get_device_conf_func: function which takes device as a parameter
                                     and returns the configuration for device
        :param device: device to detach
        :param persistent: bool to indicate whether the change is
                           persistent or not
        :param live: bool to indicate whether it affects the guest in running
                     state
        :param max_retry_count: number of times the returned function will
                                retry a detach before failing
        :param inc_sleep_time: incremental time to sleep in seconds between
                               detach retries
        :param max_sleep_time: max sleep time in seconds beyond which the sleep
                               time will not be incremented using param
                               inc_sleep_time. On reaching this threshold,
                               max_sleep_time will be used as the sleep time.
        """

        conf = get_device_conf_func(device)
        if conf is None:
            raise exception.DeviceNotFound(device=device)

        self.detach_device(conf, persistent, live)

        @loopingcall.RetryDecorator(max_retry_count=max_retry_count,
                                    inc_sleep_time=inc_sleep_time,
                                    max_sleep_time=max_sleep_time,
                                    exceptions=exception.DeviceDetachFailed)
        def _do_wait_and_retry_detach():
            config = get_device_conf_func(device)
            if config is not None:
                # Device is already detached from persistent domain
                # and only transient domain needs update
                self.detach_device(config, persistent=False, live=live)
                # Raise error since the device still existed on the guest
                reason = _("Unable to detach from guest transient domain.")
                raise exception.DeviceDetachFailed(device=device,
                                                   reason=reason)

        return _do_wait_and_retry_detach

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
        self._domain.detachDeviceFlags(conf.to_xml(), flags=flags)

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

    def _get_domain_info(self, host):
        """Returns information on Guest

        :param host: a host.Host object with current
                     connection. Unfortunately we need to pass it
                     because of a workaround with < version 1.2..11

        :returns list: [state, maxMem, memory, nrVirtCpu, cpuTime]
        """
        return compat.get_domain_info(libvirt, host, self._domain)

    def get_info(self, host):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        :returns hardware.InstanceInfo:
        """
        try:
            dom_info = self._get_domain_info(host)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=self.uuid)

            msg = (_('Error from libvirt while getting domain info for '
                     '%(instance_name)s: [Error Code %(error_code)s] %(ex)s') %
                   {'instance_name': self.name,
                    'error_code': error_code,
                    'ex': ex})
            raise exception.NovaException(msg)

        return hardware.InstanceInfo(
            state=LIBVIRT_POWER_STATE[dom_info[0]],
            max_mem_kb=dom_info[1],
            mem_kb=dom_info[2],
            num_cpu=dom_info[3],
            cpu_time_ns=dom_info[4],
            id=self.id)

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
        :param quiesce: Use QGA to quiece all mounted file systems
        """
        flags = no_metadata and (libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA
                                 or 0)
        flags |= disk_only and (libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY
                                or 0)
        flags |= reuse_ext and (libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT
                                or 0)
        flags |= quiesce and libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE or 0
        self._domain.snapshotCreateXML(conf.to_xml(), flags=flags)

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


class BlockDevice(object):
    """Wrapper around block device API"""

    REBASE_DEFAULT_BANDWIDTH = 0  # in MiB/s - 0 unlimited
    COMMIT_DEFAULT_BANDWIDTH = 0  # in MiB/s - 0 unlimited

    def __init__(self, guest, disk):
        self._guest = guest
        self._disk = disk

    def abort_job(self, async=False, pivot=False):
        """Request to cancel any job currently running on the block.

        :param async: Request only, do not wait for completion
        :param pivot: Pivot to new file when ending a copy or
                      active commit job
        """
        flags = async and libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_ASYNC or 0
        flags |= pivot and libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT or 0
        self._guest._domain.blockJobAbort(self._disk, flags=flags)

    def get_job_info(self):
        """Returns information about job currently running

        :returns: BlockDeviceJobInfo or None
        """
        status = self._guest._domain.blockJobInfo(self._disk, flags=0)
        if status != -1:
            return BlockDeviceJobInfo(
                job=status.get("type", 0),
                bandwidth=status.get("bandwidth", 0),
                cur=status.get("cur", 0),
                end=status.get("end", 0))

    def rebase(self, base, shallow=False, reuse_ext=False,
               copy=False, relative=False):
        """Rebases block to new base

        :param shallow: Limit copy to top of source backing chain
        :param reuse_ext: Reuse existing external file of a copy
        :param copy: Start a copy job
        :param relative: Keep backing chain referenced using relative names
        """
        flags = shallow and libvirt.VIR_DOMAIN_BLOCK_REBASE_SHALLOW or 0
        flags |= reuse_ext and libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT or 0
        flags |= copy and libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY or 0
        flags |= relative and libvirt.VIR_DOMAIN_BLOCK_REBASE_RELATIVE or 0
        return self._guest._domain.blockRebase(
            self._disk, base, self.REBASE_DEFAULT_BANDWIDTH, flags=flags)

    def commit(self, base, top, relative=False):
        """Commit on block device

        For performance during live snapshot it will reduces the disk chain
        to a single disk.

        :param relative: Keep backing chain referenced using relative names
        """
        flags = relative and libvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE or 0
        return self._guest._domain.blockCommit(
            self._disk, base, top, self.COMMIT_DEFAULT_BANDWIDTH, flags=flags)

    def resize(self, size_kb):
        """Resizes block device to Kib size."""
        self._guest._domain.blockResize(self._disk, size_kb)

    def wait_for_job(self, abort_on_error=False, wait_for_job_clean=False):
        """Wait for libvirt block job to complete.

        Libvirt may return either cur==end or an empty dict when
        the job is complete, depending on whether the job has been
        cleaned up by libvirt yet, or not.

        :param abort_on_error: Whether to stop process and raise NovaException
                               on error (default: False)
        :param wait_for_job_clean: Whether to force wait to ensure job is
                                   finished (see bug: LP#1119173)

        :returns: True if still in progress
                  False if completed
        """
        status = self.get_job_info()
        if not status and abort_on_error:
            msg = _('libvirt error while requesting blockjob info.')
            raise exception.NovaException(msg)

        if wait_for_job_clean:
            job_ended = status.job == 0
        else:
            job_ended = status.cur == status.end

        return not job_ended


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
