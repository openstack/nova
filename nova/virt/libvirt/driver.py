# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2011 Piston Cloud Computing, Inc
# Copyright (c) 2012 University Of Minho
# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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
A connection to a hypervisor through libvirt.

Supports KVM, LXC, QEMU, UML, XEN and Parallels.

"""

import collections
from collections import deque
import contextlib
import errno
import functools
import glob
import itertools
import mmap
import operator
import os
import shutil
import tempfile
import time
import uuid

import eventlet
from eventlet import greenthread
from eventlet import tpool
from lxml import etree
from os_brick import encryptors
from os_brick import exception as brick_exception
from os_brick.initiator import connector
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import importutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
import six
from six.moves import range

from nova.api.metadata import base as instance_metadata
from nova.api.metadata import password
from nova import block_device
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
import nova.conf
from nova.console import serial as serial_console
from nova.console import type as ctype
from nova import context as nova_context
from nova import crypto
from nova import exception
from nova.i18n import _
from nova import image
from nova import keymgr
from nova.network import model as network_model
from nova import objects
from nova.objects import diagnostics as diagnostics_obj
from nova.objects import fields
from nova.objects import migrate_data as migrate_data_obj
from nova.pci import manager as pci_manager
from nova.pci import utils as pci_utils
from nova import utils
from nova import version
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt.disk import api as disk_api
from nova.virt.disk.vfs import guestfs
from nova.virt import driver
from nova.virt import firewall
from nova.virt import hardware
from nova.virt.image import model as imgmodel
from nova.virt import images
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import firewall as libvirt_firewall
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import instancejobtracker
from nova.virt.libvirt import migration as libvirt_migrate
from nova.virt.libvirt.storage import dmcrypt
from nova.virt.libvirt.storage import lvm
from nova.virt.libvirt.storage import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt import vif as libvirt_vif
from nova.virt.libvirt.volume import mount
from nova.virt.libvirt.volume import remotefs
from nova.virt import netutils
from nova.volume import cinder

libvirt = None

uefi_logged = False

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

DEFAULT_FIREWALL_DRIVER = "%s.%s" % (
    libvirt_firewall.__name__,
    libvirt_firewall.IptablesFirewallDriver.__name__)

DEFAULT_UEFI_LOADER_PATH = {
    "x86_64": "/usr/share/OVMF/OVMF_CODE.fd",
    "aarch64": "/usr/share/AAVMF/AAVMF_CODE.fd"
}

MAX_CONSOLE_BYTES = 100 * units.Ki

# The libvirt driver will prefix any disable reason codes with this string.
DISABLE_PREFIX = 'AUTO: '
# Disable reason for the service which was enabled or disabled without reason
DISABLE_REASON_UNDEFINED = None

# Guest config console string
CONSOLE = "console=tty0 console=ttyS0 console=hvc0"

GuestNumaConfig = collections.namedtuple(
    'GuestNumaConfig', ['cpuset', 'cputune', 'numaconfig', 'numatune'])


class InjectionInfo(collections.namedtuple(
        'InjectionInfo', ['network_info', 'files', 'admin_pass'])):
    __slots__ = ()

    def __repr__(self):
        return ('InjectionInfo(network_info=%r, files=%r, '
                'admin_pass=<SANITIZED>)') % (self.network_info, self.files)

libvirt_volume_drivers = [
    'iscsi=nova.virt.libvirt.volume.iscsi.LibvirtISCSIVolumeDriver',
    'iser=nova.virt.libvirt.volume.iser.LibvirtISERVolumeDriver',
    'local=nova.virt.libvirt.volume.volume.LibvirtVolumeDriver',
    'drbd=nova.virt.libvirt.volume.drbd.LibvirtDRBDVolumeDriver',
    'fake=nova.virt.libvirt.volume.volume.LibvirtFakeVolumeDriver',
    'rbd=nova.virt.libvirt.volume.net.LibvirtNetVolumeDriver',
    'sheepdog=nova.virt.libvirt.volume.net.LibvirtNetVolumeDriver',
    'nfs=nova.virt.libvirt.volume.nfs.LibvirtNFSVolumeDriver',
    'smbfs=nova.virt.libvirt.volume.smbfs.LibvirtSMBFSVolumeDriver',
    'aoe=nova.virt.libvirt.volume.aoe.LibvirtAOEVolumeDriver',
    'fibre_channel='
        'nova.virt.libvirt.volume.fibrechannel.'
        'LibvirtFibreChannelVolumeDriver',
    'gpfs=nova.virt.libvirt.volume.gpfs.LibvirtGPFSVolumeDriver',
    'quobyte=nova.virt.libvirt.volume.quobyte.LibvirtQuobyteVolumeDriver',
    'hgst=nova.virt.libvirt.volume.hgst.LibvirtHGSTVolumeDriver',
    'scaleio=nova.virt.libvirt.volume.scaleio.LibvirtScaleIOVolumeDriver',
    'disco=nova.virt.libvirt.volume.disco.LibvirtDISCOVolumeDriver',
    'vzstorage='
        'nova.virt.libvirt.volume.vzstorage.LibvirtVZStorageVolumeDriver',
    'veritas_hyperscale='
        'nova.virt.libvirt.volume.vrtshyperscale.'
        'LibvirtHyperScaleVolumeDriver',
]


def patch_tpool_proxy():
    """eventlet.tpool.Proxy doesn't work with old-style class in __str__()
    or __repr__() calls. See bug #962840 for details.
    We perform a monkey patch to replace those two instance methods.
    """
    def str_method(self):
        return str(self._obj)

    def repr_method(self):
        return repr(self._obj)

    tpool.Proxy.__str__ = str_method
    tpool.Proxy.__repr__ = repr_method


patch_tpool_proxy()

# For information about when MIN_LIBVIRT_VERSION and
# NEXT_MIN_LIBVIRT_VERSION can be changed, consult
#
#   https://wiki.openstack.org/wiki/LibvirtDistroSupportMatrix
#
# Currently this is effectively the min version for i686/x86_64
# + KVM/QEMU, as other architectures/hypervisors require newer
# versions. Over time, this will become a common min version
# for all architectures/hypervisors, as this value rises to
# meet them.
MIN_LIBVIRT_VERSION = (1, 2, 9)
MIN_QEMU_VERSION = (2, 1, 0)
# TODO(berrange): Re-evaluate this at start of each release cycle
# to decide if we want to plan a future min version bump.
# MIN_LIBVIRT_VERSION can be updated to match this after
# NEXT_MIN_LIBVIRT_VERSION  has been at a higher value for
# one cycle
NEXT_MIN_LIBVIRT_VERSION = (1, 3, 1)
NEXT_MIN_QEMU_VERSION = (2, 5, 0)

# When the above version matches/exceeds this version
# delete it & corresponding code using it
# Libvirt version 1.2.17 is required for successful block live migration
# of vm booted from image with attached devices
MIN_LIBVIRT_BLOCK_LM_WITH_VOLUMES_VERSION = (1, 2, 17)
# PowerPC based hosts that support NUMA using libvirt
MIN_LIBVIRT_NUMA_VERSION_PPC = (1, 2, 19)
# Versions of libvirt with known NUMA topology issues
# See bug #1449028
BAD_LIBVIRT_NUMA_VERSIONS = [(1, 2, 9, 2)]
# Versions of libvirt with broken cpu pinning support. This excludes
# versions of libvirt with broken NUMA support since pinning needs
# NUMA
# See bug #1438226
BAD_LIBVIRT_CPU_POLICY_VERSIONS = [(1, 2, 10)]

# Virtuozzo driver support
MIN_VIRTUOZZO_VERSION = (7, 0, 0)
MIN_LIBVIRT_VIRTUOZZO_VERSION = (1, 2, 12)

# Ability to set the user guest password with Qemu
MIN_LIBVIRT_SET_ADMIN_PASSWD = (1, 2, 16)

# Ability to set the user guest password with parallels
MIN_LIBVIRT_PARALLELS_SET_ADMIN_PASSWD = (2, 0, 0)

# s/390 & s/390x architectures with KVM
MIN_LIBVIRT_KVM_S390_VERSION = (1, 2, 13)
MIN_QEMU_S390_VERSION = (2, 3, 0)

# libvirt < 1.3 reported virt_functions capability
# only when VFs are enabled.
# libvirt 1.3 fix f391889f4e942e22b9ef8ecca492de05106ce41e
MIN_LIBVIRT_PF_WITH_NO_VFS_CAP_VERSION = (1, 3, 0)

# Use the "logd" backend for handling stdout/stderr from QEMU processes.
MIN_LIBVIRT_VIRTLOGD = (1, 3, 3)
MIN_QEMU_VIRTLOGD = (2, 7, 0)

# ppc64/ppc64le architectures with KVM
# NOTE(rfolco): Same levels for Libvirt/Qemu on Big Endian and Little
# Endian giving the nuance around guest vs host architectures
MIN_LIBVIRT_KVM_PPC64_VERSION = (1, 2, 12)

# Names of the types that do not get compressed during migration
NO_COMPRESSION_TYPES = ('qcow2',)


# number of serial console limit
QEMU_MAX_SERIAL_PORTS = 4
# Qemu supports 4 serial consoles, we remove 1 because of the PTY one defined
ALLOWED_QEMU_SERIAL_PORTS = QEMU_MAX_SERIAL_PORTS - 1

# realtime support
MIN_LIBVIRT_REALTIME_VERSION = (1, 2, 13)

# libvirt postcopy support
MIN_LIBVIRT_POSTCOPY_VERSION = (1, 3, 3)

# qemu postcopy support
MIN_QEMU_POSTCOPY_VERSION = (2, 5, 0)

MIN_LIBVIRT_OTHER_ARCH = {
    fields.Architecture.S390: MIN_LIBVIRT_KVM_S390_VERSION,
    fields.Architecture.S390X: MIN_LIBVIRT_KVM_S390_VERSION,
    fields.Architecture.PPC: MIN_LIBVIRT_KVM_PPC64_VERSION,
    fields.Architecture.PPC64: MIN_LIBVIRT_KVM_PPC64_VERSION,
    fields.Architecture.PPC64LE: MIN_LIBVIRT_KVM_PPC64_VERSION,
}

MIN_QEMU_OTHER_ARCH = {
    fields.Architecture.S390: MIN_QEMU_S390_VERSION,
    fields.Architecture.S390X: MIN_QEMU_S390_VERSION,
}

# perf events support
MIN_LIBVIRT_PERF_VERSION = (2, 0, 0)
LIBVIRT_PERF_EVENT_PREFIX = 'VIR_PERF_PARAM_'

PERF_EVENTS_CPU_FLAG_MAPPING = {'cmt': 'cmt',
                                'mbml': 'mbm_local',
                                'mbmt': 'mbm_total',
                               }


class LibvirtDriver(driver.ComputeDriver):
    capabilities = {
        "has_imagecache": True,
        "supports_recreate": True,
        "supports_migrate_to_same_host": False,
        "supports_attach_interface": True,
        "supports_device_tagging": True,
        "supports_tagged_attach_interface": True,
        "supports_tagged_attach_volume": True,
        "supports_extend_volume": True,
    }

    def __init__(self, virtapi, read_only=False):
        super(LibvirtDriver, self).__init__(virtapi)

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')
            libvirt_migrate.libvirt = libvirt

        self._host = host.Host(self._uri(), read_only,
                               lifecycle_event_handler=self.emit_event,
                               conn_event_handler=self._handle_conn_event)
        self._initiator = None
        self._fc_wwnns = None
        self._fc_wwpns = None
        self._caps = None
        self._supported_perf_events = []
        self.firewall_driver = firewall.load_driver(
            DEFAULT_FIREWALL_DRIVER,
            host=self._host)

        self.vif_driver = libvirt_vif.LibvirtGenericVIFDriver()

        # TODO(mriedem): Long-term we should load up the volume drivers on
        # demand as needed rather than doing this on startup, as there might
        # be unsupported volume drivers in this list based on the underlying
        # platform.
        self.volume_drivers = self._get_volume_drivers()

        self._disk_cachemode = None
        self.image_cache_manager = imagecache.ImageCacheManager()
        self.image_backend = imagebackend.Backend(CONF.use_cow_images)

        self.disk_cachemodes = {}

        self.valid_cachemodes = ["default",
                                 "none",
                                 "writethrough",
                                 "writeback",
                                 "directsync",
                                 "unsafe",
                                ]
        self._conn_supports_start_paused = CONF.libvirt.virt_type in ('kvm',
                                                                      'qemu')

        for mode_str in CONF.libvirt.disk_cachemodes:
            disk_type, sep, cache_mode = mode_str.partition('=')
            if cache_mode not in self.valid_cachemodes:
                LOG.warning('Invalid cachemode %(cache_mode)s specified '
                            'for disk type %(disk_type)s.',
                            {'cache_mode': cache_mode, 'disk_type': disk_type})
                continue
            self.disk_cachemodes[disk_type] = cache_mode

        self._volume_api = cinder.API()
        self._image_api = image.API()

        sysinfo_serial_funcs = {
            'none': lambda: None,
            'hardware': self._get_host_sysinfo_serial_hardware,
            'os': self._get_host_sysinfo_serial_os,
            'auto': self._get_host_sysinfo_serial_auto,
        }

        self._sysinfo_serial_func = sysinfo_serial_funcs.get(
            CONF.libvirt.sysinfo_serial)

        self.job_tracker = instancejobtracker.InstanceJobTracker()
        self._remotefs = remotefs.RemoteFilesystem()

        self._live_migration_flags = self._block_migration_flags = 0
        self.active_migrations = {}

        # Compute reserved hugepages from conf file at the very
        # beginning to ensure any syntax error will be reported and
        # avoid any re-calculation when computing resources.
        self._reserved_hugepages = hardware.numa_get_reserved_huge_pages()

    def _get_volume_drivers(self):
        driver_registry = dict()

        for driver_str in libvirt_volume_drivers:
            driver_type, _sep, driver = driver_str.partition('=')
            driver_class = importutils.import_class(driver)
            try:
                driver_registry[driver_type] = driver_class(self._host)
            except brick_exception.InvalidConnectorProtocol:
                LOG.debug('Unable to load volume driver %s. It is not '
                          'supported on this host.', driver)

        return driver_registry

    @property
    def disk_cachemode(self):
        if self._disk_cachemode is None:
            # We prefer 'none' for consistent performance, host crash
            # safety & migration correctness by avoiding host page cache.
            # Some filesystems don't support O_DIRECT though. For those we
            # fallback to 'writethrough' which gives host crash safety, and
            # is safe for migration provided the filesystem is cache coherent
            # (cluster filesystems typically are, but things like NFS are not).
            self._disk_cachemode = "none"
            if not self._supports_direct_io(CONF.instances_path):
                self._disk_cachemode = "writethrough"
        return self._disk_cachemode

    def _set_cache_mode(self, conf):
        """Set cache mode on LibvirtConfigGuestDisk object."""
        try:
            source_type = conf.source_type
            driver_cache = conf.driver_cache
        except AttributeError:
            return

        cache_mode = self.disk_cachemodes.get(source_type,
                                              driver_cache)
        conf.driver_cache = cache_mode

    def _do_quality_warnings(self):
        """Warn about untested driver configurations.

        This will log a warning message about untested driver or host arch
        configurations to indicate to administrators that the quality is
        unknown. Currently, only qemu or kvm on intel 32- or 64-bit systems
        is tested upstream.
        """
        caps = self._host.get_capabilities()
        hostarch = caps.host.cpu.arch
        if (CONF.libvirt.virt_type not in ('qemu', 'kvm') or
            hostarch not in (fields.Architecture.I686,
                             fields.Architecture.X86_64)):
            LOG.warning('The libvirt driver is not tested on '
                        '%(type)s/%(arch)s by the OpenStack project and '
                        'thus its quality can not be ensured. For more '
                        'information, see: http://docs.openstack.org/'
                        'developer/nova/support-matrix.html',
                        {'type': CONF.libvirt.virt_type, 'arch': hostarch})

    def _handle_conn_event(self, enabled, reason):
        LOG.info("Connection event '%(enabled)d' reason '%(reason)s'",
                 {'enabled': enabled, 'reason': reason})
        self._set_host_enabled(enabled, reason)

    def _version_to_string(self, version):
        return '.'.join([str(x) for x in version])

    def init_host(self, host):
        self._host.initialize()

        self._do_quality_warnings()

        self._parse_migration_flags()

        self._supported_perf_events = self._get_supported_perf_events()

        if (CONF.libvirt.virt_type == 'lxc' and
                not (CONF.libvirt.uid_maps and CONF.libvirt.gid_maps)):
            LOG.warning("Running libvirt-lxc without user namespaces is "
                        "dangerous. Containers spawned by Nova will be run "
                        "as the host's root user. It is highly suggested "
                        "that user namespaces be used in a public or "
                        "multi-tenant environment.")

        # Stop libguestfs using KVM unless we're also configured
        # to use this. This solves problem where people need to
        # stop Nova use of KVM because nested-virt is broken
        if CONF.libvirt.virt_type != "kvm":
            guestfs.force_tcg()

        if not self._host.has_min_version(MIN_LIBVIRT_VERSION):
            raise exception.InternalError(
                _('Nova requires libvirt version %s or greater.') %
                self._version_to_string(MIN_LIBVIRT_VERSION))

        if CONF.libvirt.virt_type in ("qemu", "kvm"):
            if self._host.has_min_version(hv_ver=MIN_QEMU_VERSION):
                # "qemu-img info" calls are version dependent, so we need to
                # store the version in the images module.
                images.QEMU_VERSION = self._host.get_connection().getVersion()
            else:
                raise exception.InternalError(
                    _('Nova requires QEMU version %s or greater.') %
                    self._version_to_string(MIN_QEMU_VERSION))

        if CONF.libvirt.virt_type == 'parallels':
            if not self._host.has_min_version(hv_ver=MIN_VIRTUOZZO_VERSION):
                raise exception.InternalError(
                    _('Nova requires Virtuozzo version %s or greater.') %
                    self._version_to_string(MIN_VIRTUOZZO_VERSION))
            if not self._host.has_min_version(MIN_LIBVIRT_VIRTUOZZO_VERSION):
                raise exception.InternalError(
                    _('Running Nova with parallels virt_type requires '
                      'libvirt version %s') %
                    self._version_to_string(MIN_LIBVIRT_VIRTUOZZO_VERSION))

        # Give the cloud admin a heads up if we are intending to
        # change the MIN_LIBVIRT_VERSION in the next release.
        if not self._host.has_min_version(NEXT_MIN_LIBVIRT_VERSION):
            LOG.warning('Running Nova with a libvirt version less than '
                        '%(version)s is deprecated. The required minimum '
                        'version of libvirt will be raised to %(version)s '
                        'in the next release.',
                        {'version': self._version_to_string(
                            NEXT_MIN_LIBVIRT_VERSION)})
        if (CONF.libvirt.virt_type in ("qemu", "kvm") and
            not self._host.has_min_version(hv_ver=NEXT_MIN_QEMU_VERSION)):
            LOG.warning('Running Nova with a QEMU version less than '
                        '%(version)s is deprecated. The required minimum '
                        'version of QEMU will be raised to %(version)s '
                        'in the next release.',
                        {'version': self._version_to_string(
                            NEXT_MIN_QEMU_VERSION)})

        kvm_arch = fields.Architecture.from_host()
        if (CONF.libvirt.virt_type in ('kvm', 'qemu') and
            kvm_arch in MIN_LIBVIRT_OTHER_ARCH and
                not self._host.has_min_version(
                                        MIN_LIBVIRT_OTHER_ARCH.get(kvm_arch),
                                        MIN_QEMU_OTHER_ARCH.get(kvm_arch))):
            if MIN_QEMU_OTHER_ARCH.get(kvm_arch):
                raise exception.InternalError(
                    _('Running Nova with qemu/kvm virt_type on %(arch)s '
                      'requires libvirt version %(libvirt_ver)s and '
                      'qemu version %(qemu_ver)s, or greater') %
                    {'arch': kvm_arch,
                     'libvirt_ver': self._version_to_string(
                         MIN_LIBVIRT_OTHER_ARCH.get(kvm_arch)),
                     'qemu_ver': self._version_to_string(
                         MIN_QEMU_OTHER_ARCH.get(kvm_arch))})
            # no qemu version in the error message
            raise exception.InternalError(
                _('Running Nova with qemu/kvm virt_type on %(arch)s '
                  'requires libvirt version %(libvirt_ver)s or greater') %
                {'arch': kvm_arch,
                 'libvirt_ver': self._version_to_string(
                     MIN_LIBVIRT_OTHER_ARCH.get(kvm_arch))})

    def _prepare_migration_flags(self):
        migration_flags = 0

        migration_flags |= libvirt.VIR_MIGRATE_LIVE

        # Adding p2p flag only if xen is not in use, because xen does not
        # support p2p migrations
        if CONF.libvirt.virt_type != 'xen':
            migration_flags |= libvirt.VIR_MIGRATE_PEER2PEER

        # Adding VIR_MIGRATE_UNDEFINE_SOURCE because, without it, migrated
        # instance will remain defined on the source host
        migration_flags |= libvirt.VIR_MIGRATE_UNDEFINE_SOURCE

        # Adding VIR_MIGRATE_PERSIST_DEST to persist the VM on the
        # destination host
        migration_flags |= libvirt.VIR_MIGRATE_PERSIST_DEST

        live_migration_flags = block_migration_flags = migration_flags

        # Adding VIR_MIGRATE_NON_SHARED_INC, otherwise all block-migrations
        # will be live-migrations instead
        block_migration_flags |= libvirt.VIR_MIGRATE_NON_SHARED_INC

        return (live_migration_flags, block_migration_flags)

    def _handle_live_migration_tunnelled(self, migration_flags):
        if (CONF.libvirt.live_migration_tunnelled is None or
                CONF.libvirt.live_migration_tunnelled):
            migration_flags |= libvirt.VIR_MIGRATE_TUNNELLED
        return migration_flags

    def _is_post_copy_available(self):
        if self._host.has_min_version(lv_ver=MIN_LIBVIRT_POSTCOPY_VERSION,
                                      hv_ver=MIN_QEMU_POSTCOPY_VERSION):
            return True
        return False

    def _is_virtlogd_available(self):
        return self._host.has_min_version(MIN_LIBVIRT_VIRTLOGD,
                                          MIN_QEMU_VIRTLOGD)

    def _handle_live_migration_post_copy(self, migration_flags):
        if CONF.libvirt.live_migration_permit_post_copy:
            if self._is_post_copy_available():
                migration_flags |= libvirt.VIR_MIGRATE_POSTCOPY
            else:
                LOG.info('The live_migration_permit_post_copy is set '
                         'to True, but it is not supported.')
        return migration_flags

    def _handle_live_migration_auto_converge(self, migration_flags):
        if (self._is_post_copy_available() and
                (migration_flags & libvirt.VIR_MIGRATE_POSTCOPY) != 0):
            LOG.info('The live_migration_permit_post_copy is set to '
                     'True and post copy live migration is available '
                     'so auto-converge will not be in use.')
        elif CONF.libvirt.live_migration_permit_auto_converge:
            migration_flags |= libvirt.VIR_MIGRATE_AUTO_CONVERGE
        return migration_flags

    def _parse_migration_flags(self):
        (live_migration_flags,
            block_migration_flags) = self._prepare_migration_flags()

        live_migration_flags = self._handle_live_migration_tunnelled(
            live_migration_flags)
        block_migration_flags = self._handle_live_migration_tunnelled(
            block_migration_flags)

        live_migration_flags = self._handle_live_migration_post_copy(
            live_migration_flags)
        block_migration_flags = self._handle_live_migration_post_copy(
            block_migration_flags)

        live_migration_flags = self._handle_live_migration_auto_converge(
            live_migration_flags)
        block_migration_flags = self._handle_live_migration_auto_converge(
            block_migration_flags)

        self._live_migration_flags = live_migration_flags
        self._block_migration_flags = block_migration_flags

    # TODO(sahid): This method is targeted for removal when the tests
    # have been updated to avoid its use
    #
    # All libvirt API calls on the libvirt.Connect object should be
    # encapsulated by methods on the nova.virt.libvirt.host.Host
    # object, rather than directly invoking the libvirt APIs. The goal
    # is to avoid a direct dependency on the libvirt API from the
    # driver.py file.
    def _get_connection(self):
        return self._host.get_connection()

    _conn = property(_get_connection)

    @staticmethod
    def _uri():
        if CONF.libvirt.virt_type == 'uml':
            uri = CONF.libvirt.connection_uri or 'uml:///system'
        elif CONF.libvirt.virt_type == 'xen':
            uri = CONF.libvirt.connection_uri or 'xen:///'
        elif CONF.libvirt.virt_type == 'lxc':
            uri = CONF.libvirt.connection_uri or 'lxc:///'
        elif CONF.libvirt.virt_type == 'parallels':
            uri = CONF.libvirt.connection_uri or 'parallels:///system'
        else:
            uri = CONF.libvirt.connection_uri or 'qemu:///system'
        return uri

    @staticmethod
    def _live_migration_uri(dest):
        uris = {
            'kvm': 'qemu+%s://%s/system',
            'qemu': 'qemu+%s://%s/system',
            'xen': 'xenmigr://%s/system',
            'parallels': 'parallels+tcp://%s/system',
        }
        virt_type = CONF.libvirt.virt_type
        # TODO(pkoniszewski): Remove fetching live_migration_uri in Pike
        uri = CONF.libvirt.live_migration_uri
        if uri:
            return uri % dest

        uri = uris.get(virt_type)
        if uri is None:
            raise exception.LiveMigrationURINotAvailable(virt_type=virt_type)

        str_format = (dest,)
        if virt_type in ('kvm', 'qemu'):
            scheme = CONF.libvirt.live_migration_scheme or 'tcp'
            str_format = (scheme, dest)
        return uris.get(virt_type) % str_format

    @staticmethod
    def _migrate_uri(dest):
        uri = None
        # Only QEMU live migrations supports migrate-uri parameter
        virt_type = CONF.libvirt.virt_type
        if virt_type in ('qemu', 'kvm'):
            # QEMU accept two schemes: tcp and rdma.  By default
            # libvirt build the URI using the remote hostname and the
            # tcp schema.
            uri = 'tcp://%s' % dest
        # Because dest might be of type unicode, here we might return value of
        # type unicode as well which is not acceptable by libvirt python
        # binding when Python 2.7 is in use, so let's convert it explicitly
        # back to string. When Python 3.x is in use, libvirt python binding
        # accepts unicode type so it is completely fine to do a no-op str(uri)
        # conversion which will return value of type unicode.
        return uri and str(uri)

    def instance_exists(self, instance):
        """Efficient override of base instance_exists method."""
        try:
            self._host.get_guest(instance)
            return True
        except (exception.InternalError, exception.InstanceNotFound):
            return False

    def estimate_instance_overhead(self, instance_info):
        overhead = super(LibvirtDriver, self).estimate_instance_overhead(
            instance_info)
        if isinstance(instance_info, objects.Flavor):
            # A flavor object is passed during case of migrate
            # TODO(sahid): We do not have any way to retrieve the
            # image meta related to the instance so if the cpu_policy
            # has been set in image_meta we will get an
            # exception. Until we fix it we specifically set the
            # cpu_policy in dedicated in an ImageMeta object so if the
            # emulator threads has been requested nothing is going to
            # fail.
            image_meta = objects.ImageMeta.from_dict({"properties": {
                "hw_cpu_policy": fields.CPUAllocationPolicy.DEDICATED,
            }})
            if (hardware.get_emulator_threads_constraint(
                    instance_info, image_meta)
                == fields.CPUEmulatorThreadsPolicy.ISOLATE):
                overhead['vcpus'] += 1
        else:
            # An instance object is passed during case of spawing or a
            # dict is passed when computing resource for an instance
            numa_topology = hardware.instance_topology_from_instance(
                instance_info)
            if numa_topology and numa_topology.emulator_threads_isolated:
                overhead['vcpus'] += 1
        return overhead

    def list_instances(self):
        names = []
        for guest in self._host.list_guests(only_running=False):
            names.append(guest.name)

        return names

    def list_instance_uuids(self):
        uuids = []
        for guest in self._host.list_guests(only_running=False):
            uuids.append(guest.uuid)

        return uuids

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for vif in network_info:
            self.vif_driver.plug(instance, vif)

    def _unplug_vifs(self, instance, network_info, ignore_errors):
        """Unplug VIFs from networks."""
        for vif in network_info:
            try:
                self.vif_driver.unplug(instance, vif)
            except exception.NovaException:
                if not ignore_errors:
                    raise

    def unplug_vifs(self, instance, network_info):
        self._unplug_vifs(instance, network_info, False)

    def _teardown_container(self, instance):
        inst_path = libvirt_utils.get_instance_path(instance)
        container_dir = os.path.join(inst_path, 'rootfs')
        rootfs_dev = instance.system_metadata.get('rootfs_device_name')
        LOG.debug('Attempting to teardown container at path %(dir)s with '
                  'root device: %(rootfs_dev)s',
                  {'dir': container_dir, 'rootfs_dev': rootfs_dev},
                  instance=instance)
        disk_api.teardown_container(container_dir, rootfs_dev)

    def _destroy(self, instance, attempt=1):
        try:
            guest = self._host.get_guest(instance)
            if CONF.serial_console.enabled:
                # This method is called for several events: destroy,
                # rebuild, hard-reboot, power-off - For all of these
                # events we want to release the serial ports acquired
                # for the guest before destroying it.
                serials = self._get_serial_ports_from_guest(guest)
                for hostname, port in serials:
                    serial_console.release_port(host=hostname, port=port)
        except exception.InstanceNotFound:
            guest = None

        # If the instance is already terminated, we're still happy
        # Otherwise, destroy it
        old_domid = -1
        if guest is not None:
            try:
                old_domid = guest.id
                guest.poweroff()

            except libvirt.libvirtError as e:
                is_okay = False
                errcode = e.get_error_code()
                if errcode == libvirt.VIR_ERR_NO_DOMAIN:
                    # Domain already gone. This can safely be ignored.
                    is_okay = True
                elif errcode == libvirt.VIR_ERR_OPERATION_INVALID:
                    # If the instance is already shut off, we get this:
                    # Code=55 Error=Requested operation is not valid:
                    # domain is not running

                    state = guest.get_power_state(self._host)
                    if state == power_state.SHUTDOWN:
                        is_okay = True
                elif errcode == libvirt.VIR_ERR_INTERNAL_ERROR:
                    errmsg = e.get_error_message()
                    if (CONF.libvirt.virt_type == 'lxc' and
                        errmsg == 'internal error: '
                                  'Some processes refused to die'):
                        # Some processes in the container didn't die
                        # fast enough for libvirt. The container will
                        # eventually die. For now, move on and let
                        # the wait_for_destroy logic take over.
                        is_okay = True
                elif errcode == libvirt.VIR_ERR_OPERATION_TIMEOUT:
                    LOG.warning("Cannot destroy instance, operation time out",
                                instance=instance)
                    reason = _("operation time out")
                    raise exception.InstancePowerOffFailure(reason=reason)
                elif errcode == libvirt.VIR_ERR_SYSTEM_ERROR:
                    if e.get_int1() == errno.EBUSY:
                        # NOTE(danpb): When libvirt kills a process it sends it
                        # SIGTERM first and waits 10 seconds. If it hasn't gone
                        # it sends SIGKILL and waits another 5 seconds. If it
                        # still hasn't gone then you get this EBUSY error.
                        # Usually when a QEMU process fails to go away upon
                        # SIGKILL it is because it is stuck in an
                        # uninterruptible kernel sleep waiting on I/O from
                        # some non-responsive server.
                        # Given the CPU load of the gate tests though, it is
                        # conceivable that the 15 second timeout is too short,
                        # particularly if the VM running tempest has a high
                        # steal time from the cloud host. ie 15 wallclock
                        # seconds may have passed, but the VM might have only
                        # have a few seconds of scheduled run time.
                        LOG.warning('Error from libvirt during destroy. '
                                    'Code=%(errcode)s Error=%(e)s; '
                                    'attempt %(attempt)d of 3',
                                    {'errcode': errcode, 'e': e,
                                     'attempt': attempt},
                                    instance=instance)
                        with excutils.save_and_reraise_exception() as ctxt:
                            # Try up to 3 times before giving up.
                            if attempt < 3:
                                ctxt.reraise = False
                                self._destroy(instance, attempt + 1)
                                return

                if not is_okay:
                    with excutils.save_and_reraise_exception():
                        LOG.error('Error from libvirt during destroy. '
                                  'Code=%(errcode)s Error=%(e)s',
                                  {'errcode': errcode, 'e': e},
                                  instance=instance)

        def _wait_for_destroy(expected_domid):
            """Called at an interval until the VM is gone."""
            # NOTE(vish): If the instance disappears during the destroy
            #             we ignore it so the cleanup can still be
            #             attempted because we would prefer destroy to
            #             never fail.
            try:
                dom_info = self.get_info(instance)
                state = dom_info.state
                new_domid = dom_info.id
            except exception.InstanceNotFound:
                LOG.debug("During wait destroy, instance disappeared.",
                          instance=instance)
                state = power_state.SHUTDOWN

            if state == power_state.SHUTDOWN:
                LOG.info("Instance destroyed successfully.", instance=instance)
                raise loopingcall.LoopingCallDone()

            # NOTE(wangpan): If the instance was booted again after destroy,
            #                this may be an endless loop, so check the id of
            #                domain here, if it changed and the instance is
            #                still running, we should destroy it again.
            # see https://bugs.launchpad.net/nova/+bug/1111213 for more details
            if new_domid != expected_domid:
                LOG.info("Instance may be started again.", instance=instance)
                kwargs['is_running'] = True
                raise loopingcall.LoopingCallDone()

        kwargs = {'is_running': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_destroy,
                                                     old_domid)
        timer.start(interval=0.5).wait()
        if kwargs['is_running']:
            LOG.info("Going to destroy instance again.", instance=instance)
            self._destroy(instance)
        else:
            # NOTE(GuanQiang): teardown container to avoid resource leak
            if CONF.libvirt.virt_type == 'lxc':
                self._teardown_container(instance)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        self._destroy(instance)
        self.cleanup(context, instance, network_info, block_device_info,
                     destroy_disks)

    def _undefine_domain(self, instance):
        try:
            guest = self._host.get_guest(instance)
            try:
                support_uefi = self._has_uefi_support()
                guest.delete_configuration(support_uefi)
            except libvirt.libvirtError as e:
                with excutils.save_and_reraise_exception() as ctxt:
                    errcode = e.get_error_code()
                    if errcode == libvirt.VIR_ERR_NO_DOMAIN:
                        LOG.debug("Called undefine, but domain already gone.",
                                  instance=instance)
                        ctxt.reraise = False
                    else:
                        LOG.error('Error from libvirt during undefine. '
                                  'Code=%(errcode)s Error=%(e)s',
                                  {'errcode': errcode, 'e': e},
                                  instance=instance)
        except exception.InstanceNotFound:
            pass

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        if destroy_vifs:
            self._unplug_vifs(instance, network_info, True)

        retry = True
        while retry:
            try:
                self.unfilter_instance(instance, network_info)
            except libvirt.libvirtError as e:
                try:
                    state = self.get_info(instance).state
                except exception.InstanceNotFound:
                    state = power_state.SHUTDOWN

                if state != power_state.SHUTDOWN:
                    LOG.warning("Instance may be still running, destroy "
                                "it again.", instance=instance)
                    self._destroy(instance)
                else:
                    retry = False
                    errcode = e.get_error_code()
                    LOG.exception(_('Error from libvirt during unfilter. '
                                    'Code=%(errcode)s Error=%(e)s'),
                                  {'errcode': errcode, 'e': e},
                                  instance=instance)
                    reason = _("Error unfiltering instance.")
                    raise exception.InstanceTerminationFailure(reason=reason)
            except Exception:
                retry = False
                raise
            else:
                retry = False

        # FIXME(wangpan): if the instance is booted again here, such as the
        #                 soft reboot operation boot it here, it will become
        #                 "running deleted", should we check and destroy it
        #                 at the end of this method?

        # NOTE(vish): we disconnect from volumes regardless
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device']
            if disk_dev is not None:
                disk_dev = disk_dev.rpartition("/")[2]

            if ('data' in connection_info and
                    'volume_id' in connection_info['data']):
                volume_id = connection_info['data']['volume_id']
                encryption = encryptors.get_encryption_metadata(
                    context, self._volume_api, volume_id, connection_info)

                if encryption:
                    # The volume must be detached from the VM before
                    # disconnecting it from its encryptor. Otherwise, the
                    # encryptor may report that the volume is still in use.
                    encryptor = self._get_volume_encryptor(connection_info,
                                                           encryption)
                    try:
                        encryptor.detach_volume(**encryption)
                    except processutils.ProcessExecutionError as e:
                        if e.exit_code == 4:
                            LOG.debug('Ignoring exit code 4, volume already '
                                      'destroyed')
                        else:
                            with excutils.save_and_reraise_exception():
                                LOG.warning(
                                    'Could not disconnect encrypted volume '
                                    '%(volume)s. If the device is still '
                                    'active, it will have to destroyed '
                                    'manually for cleanup to succeed.',
                                    {'volume': disk_dev})

            try:
                self._disconnect_volume(connection_info, disk_dev, instance)
            except Exception as exc:
                with excutils.save_and_reraise_exception() as ctxt:
                    if destroy_disks:
                        # Don't block on Volume errors if we're trying to
                        # delete the instance as we may be partially created
                        # or deleted
                        ctxt.reraise = False
                        LOG.warning(
                            "Ignoring Volume Error on vol %(vol_id)s "
                            "during delete %(exc)s",
                            {'vol_id': vol.get('volume_id'), 'exc': exc},
                            instance=instance)

        if destroy_disks:
            # NOTE(haomai): destroy volumes if needed
            if CONF.libvirt.images_type == 'lvm':
                self._cleanup_lvm(instance, block_device_info)
            if CONF.libvirt.images_type == 'rbd':
                self._cleanup_rbd(instance)

        is_shared_block_storage = False
        if migrate_data and 'is_shared_block_storage' in migrate_data:
            is_shared_block_storage = migrate_data.is_shared_block_storage
        if destroy_disks or is_shared_block_storage:
            attempts = int(instance.system_metadata.get('clean_attempts',
                                                        '0'))
            success = self.delete_instance_files(instance)
            # NOTE(mriedem): This is used in the _run_pending_deletes periodic
            # task in the compute manager. The tight coupling is not great...
            instance.system_metadata['clean_attempts'] = str(attempts + 1)
            if success:
                instance.cleaned = True
            instance.save()

        self._undefine_domain(instance)

    def _detach_encrypted_volumes(self, instance, block_device_info):
        """Detaches encrypted volumes attached to instance."""
        disks = self._get_instance_disk_info(instance, block_device_info)
        encrypted_volumes = filter(dmcrypt.is_encrypted,
                                   [disk['path'] for disk in disks])
        for path in encrypted_volumes:
            dmcrypt.delete_volume(path)

    def _get_serial_ports_from_guest(self, guest, mode=None):
        """Returns an iterator over serial port(s) configured on guest.

        :param mode: Should be a value in (None, bind, connect)
        """
        xml = guest.get_xml_desc()
        tree = etree.fromstring(xml)

        # The 'serial' device is the base for x86 platforms. Other platforms
        # (e.g. kvm on system z = S390X) can only use 'console' devices.
        xpath_mode = "[@mode='%s']" % mode if mode else ""
        serial_tcp = "./devices/serial[@type='tcp']/source" + xpath_mode
        console_tcp = "./devices/console[@type='tcp']/source" + xpath_mode

        tcp_devices = tree.findall(serial_tcp)
        if len(tcp_devices) == 0:
            tcp_devices = tree.findall(console_tcp)
        for source in tcp_devices:
            yield (source.get("host"), int(source.get("service")))

    def _get_scsi_controller_max_unit(self, guest):
        """Returns the max disk unit used by scsi controller"""
        xml = guest.get_xml_desc()
        tree = etree.fromstring(xml)
        addrs = "./devices/disk[@device='disk']/address[@type='drive']"

        ret = []
        for obj in tree.findall(addrs):
            ret.append(int(obj.get('unit', 0)))
        return max(ret)

    @staticmethod
    def _get_rbd_driver():
        return rbd_utils.RBDDriver(
                pool=CONF.libvirt.images_rbd_pool,
                ceph_conf=CONF.libvirt.images_rbd_ceph_conf,
                rbd_user=CONF.libvirt.rbd_user)

    def _cleanup_rbd(self, instance):
        # NOTE(nic): On revert_resize, the cleanup steps for the root
        # volume are handled with an "rbd snap rollback" command,
        # and none of this is needed (and is, in fact, harmful) so
        # filter out non-ephemerals from the list
        if instance.task_state == task_states.RESIZE_REVERTING:
            filter_fn = lambda disk: (disk.startswith(instance.uuid) and
                                      disk.endswith('disk.local'))
        else:
            filter_fn = lambda disk: disk.startswith(instance.uuid)
        LibvirtDriver._get_rbd_driver().cleanup_volumes(filter_fn)

    def _cleanup_lvm(self, instance, block_device_info):
        """Delete all LVM disks for given instance object."""
        if instance.get('ephemeral_key_uuid') is not None:
            self._detach_encrypted_volumes(instance, block_device_info)

        disks = self._lvm_disks(instance)
        if disks:
            lvm.remove_volumes(disks)

    def _lvm_disks(self, instance):
        """Returns all LVM disks for given instance object."""
        if CONF.libvirt.images_volume_group:
            vg = os.path.join('/dev', CONF.libvirt.images_volume_group)
            if not os.path.exists(vg):
                return []
            pattern = '%s_' % instance.uuid

            def belongs_to_instance(disk):
                return disk.startswith(pattern)

            def fullpath(name):
                return os.path.join(vg, name)

            logical_volumes = lvm.list_volumes(vg)

            disks = [fullpath(disk) for disk in logical_volumes
                     if belongs_to_instance(disk)]
            return disks
        return []

    def get_volume_connector(self, instance):
        root_helper = utils.get_root_helper()
        return connector.get_connector_properties(
            root_helper, CONF.my_block_storage_ip,
            CONF.libvirt.volume_use_multipath,
            enforce_multipath=True,
            host=CONF.host)

    def _cleanup_resize(self, context, instance, network_info):
        inst_base = libvirt_utils.get_instance_path(instance)
        target = inst_base + '_resize'

        if os.path.exists(target):
            # Deletion can fail over NFS, so retry the deletion as required.
            # Set maximum attempt as 5, most test can remove the directory
            # for the second time.
            utils.execute('rm', '-rf', target, delay_on_retry=True,
                          attempts=5)

        # NOTE(mriedem): Some image backends will recreate the instance path
        # and disk.info during init, and all we need the root disk for
        # here is removing cloned snapshots which is backend-specific, so
        # check that first before initializing the image backend object. If
        # there is ever an image type that supports clone *and* re-creates
        # the instance directory and disk.info on init, this condition will
        # need to be re-visited to make sure that backend doesn't re-create
        # the disk. Refer to bugs: 1666831 1728603 1769131
        if self.image_backend.backend(CONF.libvirt.images_type).SUPPORTS_CLONE:
            root_disk = self.image_backend.by_name(instance, 'disk')
            # TODO(nic): Set ignore_errors=False in a future release.
            # It is set to True here to avoid any upgrade issues surrounding
            # instances being in pending resize state when the software is
            # updated; in that case there will be no snapshot to remove.
            # Once it can be reasonably assumed that no such instances exist
            # in the wild anymore, it should be set back to False
            # (the default) so it will throw errors, like it should.
            if root_disk.exists():
                root_disk.remove_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME,
                                      ignore_errors=True)

        if instance.host != CONF.host:
            self._undefine_domain(instance)
            self.unplug_vifs(instance, network_info)
            self.unfilter_instance(instance, network_info)

    def _get_volume_driver(self, connection_info):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        return self.volume_drivers[driver_type]

    def _connect_volume(self, connection_info, disk_info, instance):
        vol_driver = self._get_volume_driver(connection_info)
        vol_driver.connect_volume(connection_info, disk_info, instance)

    def _disconnect_volume(self, connection_info, disk_dev, instance):
        vol_driver = self._get_volume_driver(connection_info)
        vol_driver.disconnect_volume(connection_info, disk_dev, instance)

    def _extend_volume(self, connection_info, instance):
        vol_driver = self._get_volume_driver(connection_info)
        return vol_driver.extend_volume(connection_info, instance)

    def _get_volume_config(self, connection_info, disk_info):
        vol_driver = self._get_volume_driver(connection_info)
        conf = vol_driver.get_config(connection_info, disk_info)
        self._set_cache_mode(conf)
        return conf

    def _get_volume_encryptor(self, connection_info, encryption):
        root_helper = utils.get_root_helper()
        key_manager = keymgr.API(CONF)
        return encryptors.get_volume_encryptor(root_helper=root_helper,
                                               keymgr=key_manager,
                                               connection_info=connection_info,
                                               **encryption)

    def _get_volume_encryption(self, context, connection_info):
        """Get the encryption metadata dict if it is not provided
        """
        encryption = {}
        volume_id = driver_block_device.get_volume_id(connection_info)
        if volume_id:
            encryption = encryptors.get_encryption_metadata(context,
                            self._volume_api, volume_id, connection_info)
        return encryption

    def _check_discard_for_attach_volume(self, conf, instance):
        """Perform some checks for volumes configured for discard support.

        If discard is configured for the volume, and the guest is using a
        configuration known to not work, we will log a message explaining
        the reason why.
        """
        if conf.driver_discard == 'unmap' and conf.target_bus == 'virtio':
            LOG.debug('Attempting to attach volume %(id)s with discard '
                      'support enabled to an instance using an '
                      'unsupported configuration. target_bus = '
                      '%(bus)s. Trim commands will not be issued to '
                      'the storage device.',
                      {'bus': conf.target_bus,
                       'id': conf.serial},
                      instance=instance)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        guest = self._host.get_guest(instance)

        disk_dev = mountpoint.rpartition("/")[2]
        bdm = {
            'device_name': disk_dev,
            'disk_bus': disk_bus,
            'device_type': device_type}

        # Note(cfb): If the volume has a custom block size, check that
        #            that we are using QEMU/KVM and libvirt >= 0.10.2. The
        #            presence of a block size is considered mandatory by
        #            cinder so we fail if we can't honor the request.
        data = {}
        if ('data' in connection_info):
            data = connection_info['data']
        if ('logical_block_size' in data or 'physical_block_size' in data):
            if ((CONF.libvirt.virt_type != "kvm" and
                 CONF.libvirt.virt_type != "qemu")):
                msg = _("Volume sets block size, but the current "
                        "libvirt hypervisor '%s' does not support custom "
                        "block size") % CONF.libvirt.virt_type
                raise exception.InvalidHypervisorType(msg)

        disk_info = blockinfo.get_info_from_bdm(
            instance, CONF.libvirt.virt_type, instance.image_meta, bdm)
        self._connect_volume(connection_info, disk_info, instance)
        if disk_info['bus'] == 'scsi':
            disk_info['unit'] = self._get_scsi_controller_max_unit(guest) + 1

        conf = self._get_volume_config(connection_info, disk_info)

        self._check_discard_for_attach_volume(conf, instance)

        try:
            state = guest.get_power_state(self._host)
            live = state in (power_state.RUNNING, power_state.PAUSED)

            if encryption:
                encryptor = self._get_volume_encryptor(connection_info,
                                                       encryption)
                encryptor.attach_volume(context, **encryption)

            guest.attach_device(conf, persistent=True, live=live)
            # NOTE(artom) If we're attaching with a device role tag, we need to
            # rebuild device_metadata. If we're attaching without a role
            # tag, we're rebuilding it here needlessly anyways. This isn't a
            # massive deal, and it helps reduce code complexity by not having
            # to indicate to the virt driver that the attach is tagged. The
            # really important optimization of not calling the database unless
            # device_metadata has actually changed is done for us by
            # instance.save().
            instance.device_metadata = self._build_device_metadata(
                context, instance)
            instance.save()
        except Exception:
            LOG.exception(_('Failed to attach volume at mountpoint: %s'),
                          mountpoint, instance=instance)
            with excutils.save_and_reraise_exception():
                self._disconnect_volume(connection_info, disk_dev, instance)

    def _swap_volume(self, guest, disk_path, conf, resize_to):
        """Swap existing disk with a new block device."""
        dev = guest.get_block_device(disk_path)

        # Save a copy of the domain's persistent XML file. We'll use this
        # to redefine the domain if anything fails during the volume swap.
        xml = guest.get_xml_desc(dump_inactive=True, dump_sensitive=True)

        # Abort is an idempotent operation, so make sure any block
        # jobs which may have failed are ended.
        try:
            dev.abort_job()
        except Exception:
            pass

        try:
            # NOTE (rmk): blockRebase cannot be executed on persistent
            #             domains, so we need to temporarily undefine it.
            #             If any part of this block fails, the domain is
            #             re-defined regardless.
            if guest.has_persistent_configuration():
                support_uefi = self._has_uefi_support()
                guest.delete_configuration(support_uefi)

            try:
                # Start copy with VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT flag to
                # allow writing to existing external volume file. Use
                # VIR_DOMAIN_BLOCK_REBASE_COPY_DEV if it's a block device to
                # make sure XML is generated correctly (bug 1691195)
                copy_dev = conf.source_type == 'block'
                dev.rebase(conf.source_path, copy=True, reuse_ext=True,
                           copy_dev=copy_dev)
                while not dev.is_job_complete():
                    time.sleep(0.5)

                dev.abort_job(pivot=True)

            except Exception as exc:
                LOG.exception("Failure rebasing volume %(new_path)s on "
                    "%(old_path)s.", {'new_path': conf.source_path,
                                      'old_path': disk_path})
                raise exception.VolumeRebaseFailed(reason=six.text_type(exc))

            if resize_to:
                dev.resize(resize_to * units.Gi / units.Ki)

            # Make sure we will redefine the domain using the updated
            # configuration after the volume was swapped. The dump_inactive
            # keyword arg controls whether we pull the inactive (persistent)
            # or active (live) config from the domain. We want to pull the
            # live config after the volume was updated to use when we redefine
            # the domain.
            xml = guest.get_xml_desc(dump_inactive=False, dump_sensitive=True)
        finally:
            self._host.write_instance_config(xml)

    def swap_volume(self, context, old_connection_info,
                    new_connection_info, instance, mountpoint, resize_to):

        # NOTE(lyarwood): Bug #1739593 uncovered a nasty data corruption
        # issue that was fixed in Queens by Ica323b87fa85a454fca9d46ada3677f18.
        # Given the size of the bugfix it was agreed not to backport the change
        # to earlier stable branches and to instead block swap volume attempts.
        if (self._get_volume_encryption(context, old_connection_info) or
            self._get_volume_encryption(context, new_connection_info)):
            raise NotImplementedError(_("Swap volume is not supported when "
                "using encrypted volumes. For more details see "
                "https://bugs.launchpad.net/nova/+bug/1739593."))

        guest = self._host.get_guest(instance)

        disk_dev = mountpoint.rpartition("/")[2]
        if not guest.get_disk(disk_dev):
            raise exception.DiskNotFound(location=disk_dev)
        disk_info = {
            'dev': disk_dev,
            'bus': blockinfo.get_disk_bus_for_disk_dev(
                CONF.libvirt.virt_type, disk_dev),
            'type': 'disk',
            }
        # NOTE (lyarwood): new_connection_info will be modified by the
        # following _connect_volume call down into the volume drivers. The
        # majority of the volume drivers will add a device_path that is in turn
        # used by _get_volume_config to set the source_path of the
        # LibvirtConfigGuestDisk object it returns. We do not explicitly save
        # this to the BDM here as the upper compute swap_volume method will
        # eventually do this for us.
        self._connect_volume(new_connection_info, disk_info, instance)
        conf = self._get_volume_config(new_connection_info, disk_info)
        if not conf.source_path:
            self._disconnect_volume(new_connection_info, disk_dev, instance)
            raise NotImplementedError(_("Swap only supports host devices"))

        try:
            self._swap_volume(guest, disk_dev, conf, resize_to)
        except exception.VolumeRebaseFailed:
            with excutils.save_and_reraise_exception():
                self._disconnect_volume(new_connection_info, disk_dev,
                                        instance)

        self._disconnect_volume(old_connection_info, disk_dev, instance)

    def _get_existing_domain_xml(self, instance, network_info,
                                 block_device_info=None):
        try:
            guest = self._host.get_guest(instance)
            xml = guest.get_xml_desc()
        except exception.InstanceNotFound:
            disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                instance,
                                                instance.image_meta,
                                                block_device_info)
            xml = self._get_guest_xml(nova_context.get_admin_context(),
                                      instance, network_info, disk_info,
                                      instance.image_meta,
                                      block_device_info=block_device_info)
        return xml

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        disk_dev = mountpoint.rpartition("/")[2]
        try:
            guest = self._host.get_guest(instance)

            state = guest.get_power_state(self._host)
            live = state in (power_state.RUNNING, power_state.PAUSED)

            # The volume must be detached from the VM before disconnecting it
            # from its encryptor. Otherwise, the encryptor may report that the
            # volume is still in use.
            wait_for_detach = guest.detach_device_with_retry(guest.get_disk,
                                                             disk_dev,
                                                             live=live)
            wait_for_detach()

        except exception.InstanceNotFound:
            # NOTE(zhaoqin): If the instance does not exist, _lookup_by_name()
            #                will throw InstanceNotFound exception. Need to
            #                disconnect volume under this circumstance.
            LOG.warning("During detach_volume, instance disappeared.",
                        instance=instance)
        except exception.DeviceNotFound:
            # We should still try to disconnect logical device from
            # host, an error might have happened during a previous
            # call.
            LOG.info("Device %s not found in instance.",
                     disk_dev, instance=instance)
        except libvirt.libvirtError as ex:
            # NOTE(vish): This is called to cleanup volumes after live
            #             migration, so we should still disconnect even if
            #             the instance doesn't exist here anymore.
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                # NOTE(vish):
                LOG.warning("During detach_volume, instance disappeared.",
                            instance=instance)
            else:
                raise

        try:
            if encryption:
                encryptor = self._get_volume_encryptor(connection_info,
                                                       encryption)
                encryptor.detach_volume(**encryption)
        except processutils.ProcessExecutionError as e:
            # cryptsetup returns 4 when attempting to destroy a non-existent
            # dm-crypt device. We assume here that the caller hasn't specified
            # the wrong device, and that it doesn't exist because it has
            # already been destroyed.
            if e.exit_code == 4:
                LOG.debug("Ignoring exit code 4, volume already destroyed")
            else:
                with excutils.save_and_reraise_exception():
                    LOG.warning("Could not disconnect encrypted volume "
                                "%(volume)s. If dm-crypt device is still "
                                "active it will have to be destroyed manually "
                                "for cleanup to succeed.",
                                {'volume': disk_dev})

        self._disconnect_volume(connection_info, disk_dev, instance)

    def extend_volume(self, connection_info, instance):
        try:
            new_size = self._extend_volume(connection_info, instance)
        except NotImplementedError:
            raise exception.ExtendVolumeNotSupported()

        # Resize the device in QEMU so its size is updated and
        # detected by the instance without rebooting.
        try:
            guest = self._host.get_guest(instance)
            state = guest.get_power_state(self._host)
            active_state = state in (power_state.RUNNING, power_state.PAUSED)
            if active_state:
                disk_path = connection_info['data']['device_path']
                LOG.debug('resizing block device %(dev)s to %(size)u kb',
                          {'dev': disk_path, 'size': new_size})
                dev = guest.get_block_device(disk_path)
                dev.resize(new_size // units.Ki)
            else:
                LOG.debug('Skipping block device resize, guest is not running',
                          instance=instance)
        except exception.InstanceNotFound:
            with excutils.save_and_reraise_exception():
                LOG.warning('During extend_volume, instance disappeared.',
                            instance=instance)
        except libvirt.libvirtError:
            with excutils.save_and_reraise_exception():
                LOG.exception('resizing block device failed.',
                              instance=instance)

    def attach_interface(self, context, instance, image_meta, vif):
        guest = self._host.get_guest(instance)

        self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(instance, [vif])
        cfg = self.vif_driver.get_config(instance, vif, image_meta,
                                         instance.flavor,
                                         CONF.libvirt.virt_type,
                                         self._host)
        try:
            state = guest.get_power_state(self._host)
            live = state in (power_state.RUNNING, power_state.PAUSED)
            guest.attach_device(cfg, persistent=True, live=live)
        except libvirt.libvirtError:
            LOG.error('attaching network adapter failed.',
                      instance=instance, exc_info=True)
            self.vif_driver.unplug(instance, vif)
            raise exception.InterfaceAttachFailed(
                    instance_uuid=instance.uuid)
        try:
            # NOTE(artom) If we're attaching with a device role tag, we need to
            # rebuild device_metadata. If we're attaching without a role
            # tag, we're rebuilding it here needlessly anyways. This isn't a
            # massive deal, and it helps reduce code complexity by not having
            # to indicate to the virt driver that the attach is tagged. The
            # really important optimization of not calling the database unless
            # device_metadata has actually changed is done for us by
            # instance.save().
            instance.device_metadata = self._build_device_metadata(
                context, instance)
            instance.save()
        except Exception:
            # NOTE(artom) If we fail here it means the interface attached
            # successfully but building and/or saving the device metadata
            # failed. Just unplugging the vif is therefore not enough cleanup,
            # we need to detach the interface.
            with excutils.save_and_reraise_exception(reraise=False):
                LOG.error('Interface attached successfully but building '
                          'and/or saving device metadata failed.',
                          instance=instance, exc_info=True)
                self.detach_interface(context, instance, vif)
                raise exception.InterfaceAttachFailed(
                    instance_uuid=instance.uuid)

    def detach_interface(self, context, instance, vif):
        guest = self._host.get_guest(instance)
        cfg = self.vif_driver.get_config(instance, vif,
                                         instance.image_meta,
                                         instance.flavor,
                                         CONF.libvirt.virt_type, self._host)
        interface = guest.get_interface_by_cfg(cfg)
        try:
            self.vif_driver.unplug(instance, vif)
            # NOTE(mriedem): When deleting an instance and using Neutron,
            # we can be racing against Neutron deleting the port and
            # sending the vif-deleted event which then triggers a call to
            # detach the interface, so if the interface is not found then
            # we can just log it as a warning.
            if not interface:
                mac = vif.get('address')
                # The interface is gone so just log it as a warning.
                LOG.warning('Detaching interface %(mac)s failed because '
                            'the device is no longer found on the guest.',
                            {'mac': mac}, instance=instance)
                return

            state = guest.get_power_state(self._host)
            live = state in (power_state.RUNNING, power_state.PAUSED)
            # Now we are going to loop until the interface is detached or we
            # timeout.
            wait_for_detach = guest.detach_device_with_retry(
                guest.get_interface_by_cfg, cfg, live=live,
                alternative_device_name=self.vif_driver.get_vif_devname(vif))
            wait_for_detach()
        except exception.DeviceDetachFailed:
            # We failed to detach the device even with the retry loop, so let's
            # dump some debug information to the logs before raising back up.
            with excutils.save_and_reraise_exception():
                devname = self.vif_driver.get_vif_devname(vif)
                interface = guest.get_interface_by_cfg(cfg)
                if interface:
                    LOG.warning(
                        'Failed to detach interface %(devname)s after '
                        'repeated attempts. Final interface xml:\n'
                        '%(interface_xml)s\nFinal guest xml:\n%(guest_xml)s',
                        {'devname': devname,
                         'interface_xml': interface.to_xml(),
                         'guest_xml': guest.get_xml_desc()},
                        instance=instance)
        except exception.DeviceNotFound:
            # The interface is gone so just log it as a warning.
            LOG.warning('Detaching interface %(mac)s failed because '
                        'the device is no longer found on the guest.',
                        {'mac': vif.get('address')}, instance=instance)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                LOG.warning("During detach_interface, instance disappeared.",
                            instance=instance)
            else:
                # NOTE(mriedem): When deleting an instance and using Neutron,
                # we can be racing against Neutron deleting the port and
                # sending the vif-deleted event which then triggers a call to
                # detach the interface, so we might have failed because the
                # network device no longer exists. Libvirt will fail with
                # "operation failed: no matching network device was found"
                # which unfortunately does not have a unique error code so we
                # need to look up the interface by config and if it's not found
                # then we can just log it as a warning rather than tracing an
                # error.
                mac = vif.get('address')
                interface = guest.get_interface_by_cfg(cfg)
                if interface:
                    LOG.error('detaching network adapter failed.',
                              instance=instance, exc_info=True)
                    raise exception.InterfaceDetachFailed(
                            instance_uuid=instance.uuid)

                # The interface is gone so just log it as a warning.
                LOG.warning('Detaching interface %(mac)s failed because '
                            'the device is no longer found on the guest.',
                            {'mac': mac}, instance=instance)

    def _create_snapshot_metadata(self, image_meta, instance,
                                  img_fmt, snp_name):
        metadata = {'is_public': False,
                    'status': 'active',
                    'name': snp_name,
                    'properties': {
                                   'kernel_id': instance.kernel_id,
                                   'image_location': 'snapshot',
                                   'image_state': 'available',
                                   'owner_id': instance.project_id,
                                   'ramdisk_id': instance.ramdisk_id,
                                   }
                    }
        if instance.os_type:
            metadata['properties']['os_type'] = instance.os_type

        # NOTE(vish): glance forces ami disk format to be ami
        if image_meta.disk_format == 'ami':
            metadata['disk_format'] = 'ami'
        else:
            metadata['disk_format'] = img_fmt

        if image_meta.obj_attr_is_set("container_format"):
            metadata['container_format'] = image_meta.container_format
        else:
            metadata['container_format'] = "bare"

        return metadata

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance.

        This command only works with qemu 0.14+
        """
        try:
            guest = self._host.get_guest(instance)

            # TODO(sahid): We are converting all calls from a
            # virDomain object to use nova.virt.libvirt.Guest.
            # We should be able to remove virt_dom at the end.
            virt_dom = guest._domain
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)

        snapshot = self._image_api.get(context, image_id)

        # source_format is an on-disk format
        # source_type is a backend type
        disk_path, source_format = libvirt_utils.find_disk(guest)
        source_type = libvirt_utils.get_disk_type_from_path(disk_path)

        # We won't have source_type for raw or qcow2 disks, because we can't
        # determine that from the path. We should have it from the libvirt
        # xml, though.
        if source_type is None:
            source_type = source_format
        # For lxc instances we won't have it either from libvirt xml
        # (because we just gave libvirt the mounted filesystem), or the path,
        # so source_type is still going to be None. In this case,
        # root_disk is going to default to CONF.libvirt.images_type
        # below, which is still safe.

        image_format = CONF.libvirt.snapshot_image_format or source_type

        # NOTE(bfilippov): save lvm and rbd as raw
        if image_format == 'lvm' or image_format == 'rbd':
            image_format = 'raw'

        metadata = self._create_snapshot_metadata(instance.image_meta,
                                                  instance,
                                                  image_format,
                                                  snapshot['name'])

        snapshot_name = uuid.uuid4().hex

        state = guest.get_power_state(self._host)

        # NOTE(dgenin): Instances with LVM encrypted ephemeral storage require
        #               cold snapshots. Currently, checking for encryption is
        #               redundant because LVM supports only cold snapshots.
        #               It is necessary in case this situation changes in the
        #               future.
        if (self._host.has_min_version(hv_type=host.HV_DRIVER_QEMU)
             and source_type not in ('lvm')
             and not CONF.ephemeral_storage_encryption.enabled
             and not CONF.workarounds.disable_libvirt_livesnapshot):
            live_snapshot = True
            # Abort is an idempotent operation, so make sure any block
            # jobs which may have failed are ended. This operation also
            # confirms the running instance, as opposed to the system as a
            # whole, has a new enough version of the hypervisor (bug 1193146).
            try:
                guest.get_block_device(disk_path).abort_job()
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_CONFIG_UNSUPPORTED:
                    live_snapshot = False
                else:
                    pass
        else:
            live_snapshot = False

        # NOTE(rmk): We cannot perform live snapshots when a managedSave
        #            file is present, so we will use the cold/legacy method
        #            for instances which are shutdown.
        if state == power_state.SHUTDOWN:
            live_snapshot = False

        self._prepare_domain_for_snapshot(context, live_snapshot, state,
                                          instance)

        root_disk = self.image_backend.by_libvirt_path(
            instance, disk_path, image_type=source_type)

        if live_snapshot:
            LOG.info("Beginning live snapshot process", instance=instance)
        else:
            LOG.info("Beginning cold snapshot process", instance=instance)

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        try:
            update_task_state(task_state=task_states.IMAGE_UPLOADING,
                              expected_state=task_states.IMAGE_PENDING_UPLOAD)
            metadata['location'] = root_disk.direct_snapshot(
                context, snapshot_name, image_format, image_id,
                instance.image_ref)
            self._snapshot_domain(context, live_snapshot, virt_dom, state,
                                  instance)
            self._image_api.update(context, image_id, metadata,
                                   purge_props=False)
        except (NotImplementedError, exception.ImageUnacceptable,
                exception.Forbidden) as e:
            if type(e) != NotImplementedError:
                LOG.warning('Performing standard snapshot because direct '
                            'snapshot failed: %(error)s', {'error': e})
            failed_snap = metadata.pop('location', None)
            if failed_snap:
                failed_snap = {'url': str(failed_snap)}
            root_disk.cleanup_direct_snapshot(failed_snap,
                                                  also_destroy_volume=True,
                                                  ignore_errors=True)
            update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD,
                              expected_state=task_states.IMAGE_UPLOADING)

            # TODO(nic): possibly abstract this out to the root_disk
            if source_type == 'rbd' and live_snapshot:
                # Standard snapshot uses qemu-img convert from RBD which is
                # not safe to run with live_snapshot.
                live_snapshot = False
                # Suspend the guest, so this is no longer a live snapshot
                self._prepare_domain_for_snapshot(context, live_snapshot,
                                                  state, instance)

            snapshot_directory = CONF.libvirt.snapshots_directory
            fileutils.ensure_tree(snapshot_directory)
            with utils.tempdir(dir=snapshot_directory) as tmpdir:
                try:
                    out_path = os.path.join(tmpdir, snapshot_name)
                    if live_snapshot:
                        # NOTE(xqueralt): libvirt needs o+x in the tempdir
                        os.chmod(tmpdir, 0o701)
                        self._live_snapshot(context, instance, guest,
                                            disk_path, out_path, source_format,
                                            image_format, instance.image_meta)
                    else:
                        root_disk.snapshot_extract(out_path, image_format)
                finally:
                    self._snapshot_domain(context, live_snapshot, virt_dom,
                                          state, instance)
                    LOG.info("Snapshot extracted, beginning image upload",
                             instance=instance)

                # Upload that image to the image service
                update_task_state(task_state=task_states.IMAGE_UPLOADING,
                        expected_state=task_states.IMAGE_PENDING_UPLOAD)
                with libvirt_utils.file_open(out_path, 'rb') as image_file:
                    self._image_api.update(context,
                                           image_id,
                                           metadata,
                                           image_file)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_("Failed to snapshot image"))
                failed_snap = metadata.pop('location', None)
                if failed_snap:
                    failed_snap = {'url': str(failed_snap)}
                root_disk.cleanup_direct_snapshot(
                        failed_snap, also_destroy_volume=True,
                        ignore_errors=True)

        LOG.info("Snapshot image upload complete", instance=instance)

    def _prepare_domain_for_snapshot(self, context, live_snapshot, state,
                                     instance):
        # NOTE(dkang): managedSave does not work for LXC
        if CONF.libvirt.virt_type != 'lxc' and not live_snapshot:
            if state == power_state.RUNNING or state == power_state.PAUSED:
                self.suspend(context, instance)

    def _snapshot_domain(self, context, live_snapshot, virt_dom, state,
                         instance):
        guest = None
        # NOTE(dkang): because previous managedSave is not called
        #              for LXC, _create_domain must not be called.
        if CONF.libvirt.virt_type != 'lxc' and not live_snapshot:
            if state == power_state.RUNNING:
                guest = self._create_domain(domain=virt_dom)
            elif state == power_state.PAUSED:
                guest = self._create_domain(domain=virt_dom, pause=True)

            if guest is not None:
                self._attach_pci_devices(
                    guest, pci_manager.get_instance_pci_devs(instance))
                self._attach_direct_passthrough_ports(
                    context, instance, guest)

    def _can_set_admin_password(self, image_meta):

        if CONF.libvirt.virt_type == 'parallels':
            if not self._host.has_min_version(
                   MIN_LIBVIRT_PARALLELS_SET_ADMIN_PASSWD):
                raise exception.SetAdminPasswdNotSupported()
        elif CONF.libvirt.virt_type in ('kvm', 'qemu'):
            if not self._host.has_min_version(
                   MIN_LIBVIRT_SET_ADMIN_PASSWD):
                raise exception.SetAdminPasswdNotSupported()
            if not image_meta.properties.get('hw_qemu_guest_agent', False):
                raise exception.QemuGuestAgentNotEnabled()
        else:
            raise exception.SetAdminPasswdNotSupported()

    # TODO(melwitt): Combine this with the similar xenapi code at some point.
    def _save_instance_password_if_sshkey_present(self, instance, new_pass):
        sshkey = instance.key_data if 'key_data' in instance else None
        if sshkey and sshkey.startswith("ssh-rsa"):
            enc = crypto.ssh_encrypt_text(sshkey, new_pass)
            # NOTE(melwitt): The convert_password method doesn't actually do
            # anything with the context argument, so we can pass None.
            instance.system_metadata.update(
                password.convert_password(None, base64.encode_as_text(enc)))
            instance.save()

    def set_admin_password(self, instance, new_pass):
        self._can_set_admin_password(instance.image_meta)

        guest = self._host.get_guest(instance)
        user = instance.image_meta.properties.get("os_admin_user")
        if not user:
            if instance.os_type == "windows":
                user = "Administrator"
            else:
                user = "root"
        try:
            guest.set_user_password(user, new_pass)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            err_msg = encodeutils.exception_to_unicode(ex)
            msg = (_('Error from libvirt while set password for username '
                     '"%(user)s": [Error Code %(error_code)s] %(ex)s')
                   % {'user': user, 'error_code': error_code, 'ex': err_msg})
            raise exception.InternalError(msg)
        else:
            # Save the password in sysmeta so it may be retrieved from the
            # metadata service.
            self._save_instance_password_if_sshkey_present(instance, new_pass)

    def _can_quiesce(self, instance, image_meta):
        if CONF.libvirt.virt_type not in ('kvm', 'qemu'):
            raise exception.InstanceQuiesceNotSupported(
                instance_id=instance.uuid)

        if not image_meta.properties.get('hw_qemu_guest_agent', False):
            raise exception.QemuGuestAgentNotEnabled()

    def _requires_quiesce(self, image_meta):
        return image_meta.properties.get('os_require_quiesce', False)

    def _set_quiesced(self, context, instance, image_meta, quiesced):
        self._can_quiesce(instance, image_meta)
        try:
            guest = self._host.get_guest(instance)
            if quiesced:
                guest.freeze_filesystems()
            else:
                guest.thaw_filesystems()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            err_msg = encodeutils.exception_to_unicode(ex)
            msg = (_('Error from libvirt while quiescing %(instance_name)s: '
                     '[Error Code %(error_code)s] %(ex)s')
                   % {'instance_name': instance.name,
                      'error_code': error_code, 'ex': err_msg})
            raise exception.InternalError(msg)

    def quiesce(self, context, instance, image_meta):
        """Freeze the guest filesystems to prepare for snapshot.

        The qemu-guest-agent must be setup to execute fsfreeze.
        """
        self._set_quiesced(context, instance, image_meta, True)

    def unquiesce(self, context, instance, image_meta):
        """Thaw the guest filesystems after snapshot."""
        self._set_quiesced(context, instance, image_meta, False)

    def _live_snapshot(self, context, instance, guest, disk_path, out_path,
                       source_format, image_format, image_meta):
        """Snapshot an instance without downtime."""
        dev = guest.get_block_device(disk_path)

        # Save a copy of the domain's persistent XML file
        xml = guest.get_xml_desc(dump_inactive=True, dump_sensitive=True)

        # Abort is an idempotent operation, so make sure any block
        # jobs which may have failed are ended.
        try:
            dev.abort_job()
        except Exception:
            pass

        # NOTE (rmk): We are using shallow rebases as a workaround to a bug
        #             in QEMU 1.3. In order to do this, we need to create
        #             a destination image with the original backing file
        #             and matching size of the instance root disk.
        src_disk_size = libvirt_utils.get_disk_size(disk_path,
                                                    format=source_format)
        src_back_path = libvirt_utils.get_disk_backing_file(disk_path,
                                                        format=source_format,
                                                        basename=False)
        disk_delta = out_path + '.delta'
        libvirt_utils.create_cow_image(src_back_path, disk_delta,
                                       src_disk_size)

        quiesced = False
        try:
            self._set_quiesced(context, instance, image_meta, True)
            quiesced = True
        except exception.NovaException as err:
            if self._requires_quiesce(image_meta):
                raise
            LOG.info('Skipping quiescing instance: %(reason)s.',
                     {'reason': err}, instance=instance)

        try:
            # NOTE (rmk): blockRebase cannot be executed on persistent
            #             domains, so we need to temporarily undefine it.
            #             If any part of this block fails, the domain is
            #             re-defined regardless.
            if guest.has_persistent_configuration():
                support_uefi = self._has_uefi_support()
                guest.delete_configuration(support_uefi)

            # NOTE (rmk): Establish a temporary mirror of our root disk and
            #             issue an abort once we have a complete copy.
            dev.rebase(disk_delta, copy=True, reuse_ext=True, shallow=True)

            while not dev.is_job_complete():
                time.sleep(0.5)

            dev.abort_job()
            libvirt_utils.chown(disk_delta, os.getuid())
        finally:
            self._host.write_instance_config(xml)
            if quiesced:
                self._set_quiesced(context, instance, image_meta, False)

        # Convert the delta (CoW) image with a backing file to a flat
        # image with no backing file.
        libvirt_utils.extract_snapshot(disk_delta, 'qcow2',
                                       out_path, image_format)

    def _volume_snapshot_update_status(self, context, snapshot_id, status):
        """Send a snapshot status update to Cinder.

        This method captures and logs exceptions that occur
        since callers cannot do anything useful with these exceptions.

        Operations on the Cinder side waiting for this will time out if
        a failure occurs sending the update.

        :param context: security context
        :param snapshot_id: id of snapshot being updated
        :param status: new status value

        """

        try:
            self._volume_api.update_snapshot_status(context,
                                                    snapshot_id,
                                                    status)
        except Exception:
            LOG.exception(_('Failed to send updated snapshot status '
                            'to volume service.'))

    def _volume_snapshot_create(self, context, instance, guest,
                                volume_id, new_file):
        """Perform volume snapshot.

           :param guest: VM that volume is attached to
           :param volume_id: volume UUID to snapshot
           :param new_file: relative path to new qcow2 file present on share

        """
        xml = guest.get_xml_desc()
        xml_doc = etree.fromstring(xml)

        device_info = vconfig.LibvirtConfigGuest()
        device_info.parse_dom(xml_doc)

        disks_to_snap = []          # to be snapshotted by libvirt
        network_disks_to_snap = []  # network disks (netfs, etc.)
        disks_to_skip = []          # local disks not snapshotted

        for guest_disk in device_info.devices:
            if (guest_disk.root_name != 'disk'):
                continue

            if (guest_disk.target_dev is None):
                continue

            if (guest_disk.serial is None or guest_disk.serial != volume_id):
                disks_to_skip.append(guest_disk.target_dev)
                continue

            # disk is a Cinder volume with the correct volume_id

            disk_info = {
                'dev': guest_disk.target_dev,
                'serial': guest_disk.serial,
                'current_file': guest_disk.source_path,
                'source_protocol': guest_disk.source_protocol,
                'source_name': guest_disk.source_name,
                'source_hosts': guest_disk.source_hosts,
                'source_ports': guest_disk.source_ports
            }

            # Determine path for new_file based on current path
            if disk_info['current_file'] is not None:
                current_file = disk_info['current_file']
                new_file_path = os.path.join(os.path.dirname(current_file),
                                             new_file)
                disks_to_snap.append((current_file, new_file_path))
            # NOTE(mriedem): This used to include a check for gluster in
            # addition to netfs since they were added together. Support for
            # gluster was removed in the 16.0.0 Pike release. It is unclear,
            # however, if other volume drivers rely on the netfs disk source
            # protocol.
            elif disk_info['source_protocol'] == 'netfs':
                network_disks_to_snap.append((disk_info, new_file))

        if not disks_to_snap and not network_disks_to_snap:
            msg = _('Found no disk to snapshot.')
            raise exception.InternalError(msg)

        snapshot = vconfig.LibvirtConfigGuestSnapshot()

        for current_name, new_filename in disks_to_snap:
            snap_disk = vconfig.LibvirtConfigGuestSnapshotDisk()
            snap_disk.name = current_name
            snap_disk.source_path = new_filename
            snap_disk.source_type = 'file'
            snap_disk.snapshot = 'external'
            snap_disk.driver_name = 'qcow2'

            snapshot.add_disk(snap_disk)

        for disk_info, new_filename in network_disks_to_snap:
            snap_disk = vconfig.LibvirtConfigGuestSnapshotDisk()
            snap_disk.name = disk_info['dev']
            snap_disk.source_type = 'network'
            snap_disk.source_protocol = disk_info['source_protocol']
            snap_disk.snapshot = 'external'
            snap_disk.source_path = new_filename
            old_dir = disk_info['source_name'].split('/')[0]
            snap_disk.source_name = '%s/%s' % (old_dir, new_filename)
            snap_disk.source_hosts = disk_info['source_hosts']
            snap_disk.source_ports = disk_info['source_ports']

            snapshot.add_disk(snap_disk)

        for dev in disks_to_skip:
            snap_disk = vconfig.LibvirtConfigGuestSnapshotDisk()
            snap_disk.name = dev
            snap_disk.snapshot = 'no'

            snapshot.add_disk(snap_disk)

        snapshot_xml = snapshot.to_xml()
        LOG.debug("snap xml: %s", snapshot_xml, instance=instance)

        image_meta = instance.image_meta
        try:
            # Check to see if we can quiesce the guest before taking the
            # snapshot.
            self._can_quiesce(instance, image_meta)
            try:
                guest.snapshot(snapshot, no_metadata=True, disk_only=True,
                               reuse_ext=True, quiesce=True)
                return
            except libvirt.libvirtError:
                # If the image says that quiesce is required then we fail.
                if self._requires_quiesce(image_meta):
                    raise
                LOG.exception(_('Unable to create quiesced VM snapshot, '
                                'attempting again with quiescing disabled.'),
                              instance=instance)
        except (exception.InstanceQuiesceNotSupported,
                exception.QemuGuestAgentNotEnabled) as err:
            # If the image says that quiesce is required then we need to fail.
            if self._requires_quiesce(image_meta):
                raise
            LOG.info('Skipping quiescing instance: %(reason)s.',
                     {'reason': err}, instance=instance)

        try:
            guest.snapshot(snapshot, no_metadata=True, disk_only=True,
                           reuse_ext=True, quiesce=False)
        except libvirt.libvirtError:
            LOG.exception(_('Unable to create VM snapshot, '
                            'failing volume_snapshot operation.'),
                          instance=instance)

            raise

    def _volume_refresh_connection_info(self, context, instance, volume_id):
        bdm = objects.BlockDeviceMapping.get_by_volume_and_instance(
                  context, volume_id, instance.uuid)

        driver_bdm = driver_block_device.convert_volume(bdm)
        if driver_bdm:
            driver_bdm.refresh_connection_info(context, instance,
                                               self._volume_api, self)

    def volume_snapshot_create(self, context, instance, volume_id,
                               create_info):
        """Create snapshots of a Cinder volume via libvirt.

        :param instance: VM instance object reference
        :param volume_id: id of volume being snapshotted
        :param create_info: dict of information used to create snapshots
                     - snapshot_id : ID of snapshot
                     - type : qcow2 / <other>
                     - new_file : qcow2 file created by Cinder which
                     becomes the VM's active image after
                     the snapshot is complete
        """

        LOG.debug("volume_snapshot_create: create_info: %(c_info)s",
                  {'c_info': create_info}, instance=instance)

        try:
            guest = self._host.get_guest(instance)
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)

        if create_info['type'] != 'qcow2':
            msg = _('Unknown type: %s') % create_info['type']
            raise exception.InternalError(msg)

        snapshot_id = create_info.get('snapshot_id', None)
        if snapshot_id is None:
            msg = _('snapshot_id required in create_info')
            raise exception.InternalError(msg)

        try:
            self._volume_snapshot_create(context, instance, guest,
                                         volume_id, create_info['new_file'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Error occurred during '
                                'volume_snapshot_create, '
                                'sending error status to Cinder.'),
                              instance=instance)
                self._volume_snapshot_update_status(
                    context, snapshot_id, 'error')

        self._volume_snapshot_update_status(
            context, snapshot_id, 'creating')

        def _wait_for_snapshot():
            snapshot = self._volume_api.get_snapshot(context, snapshot_id)

            if snapshot.get('status') != 'creating':
                self._volume_refresh_connection_info(context, instance,
                                                     volume_id)
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_snapshot)
        timer.start(interval=0.5).wait()

    @staticmethod
    def _rebase_with_qemu_img(guest, device, active_disk_object,
                              rebase_base):
        """Rebase a device tied to a guest using qemu-img.

        :param guest:the Guest which owns the device being rebased
        :type guest: nova.virt.libvirt.guest.Guest
        :param device: the guest block device to rebase
        :type device: nova.virt.libvirt.guest.BlockDevice
        :param active_disk_object: the guest block device to rebase
        :type active_disk_object: nova.virt.libvirt.config.\
                                    LibvirtConfigGuestDisk
        :param rebase_base: the new parent in the backing chain
        :type rebase_base: None or string
        """

        # It's unsure how well qemu-img handles network disks for
        # every protocol. So let's be safe.
        active_protocol = active_disk_object.source_protocol
        if active_protocol is not None:
            msg = _("Something went wrong when deleting a volume snapshot: "
                    "rebasing a %(protocol)s network disk using qemu-img "
                    "has not been fully tested") % {'protocol':
                    active_protocol}
            LOG.error(msg)
            raise exception.InternalError(msg)

        if rebase_base is None:
            # If backing_file is specified as "" (the empty string), then
            # the image is rebased onto no backing file (i.e. it will exist
            # independently of any backing file).
            backing_file = ""
            qemu_img_extra_arg = []
        else:
            # If the rebased image is going to have a backing file then
            # explicitly set the backing file format to avoid any security
            # concerns related to file format auto detection.
            backing_file = rebase_base
            b_file_fmt = images.qemu_img_info(backing_file).file_format
            qemu_img_extra_arg = ['-F', b_file_fmt]

        qemu_img_extra_arg.append(active_disk_object.source_path)
        utils.execute("qemu-img", "rebase", "-b", backing_file,
                      *qemu_img_extra_arg)

    def _volume_snapshot_delete(self, context, instance, volume_id,
                                snapshot_id, delete_info=None):
        """Note:
            if file being merged into == active image:
                do a blockRebase (pull) operation
            else:
                do a blockCommit operation
            Files must be adjacent in snap chain.

        :param instance: instance object reference
        :param volume_id: volume UUID
        :param snapshot_id: snapshot UUID (unused currently)
        :param delete_info: {
            'type':              'qcow2',
            'file_to_merge':     'a.img',
            'merge_target_file': 'b.img' or None (if merging file_to_merge into
                                                  active image)
          }
        """

        LOG.debug('volume_snapshot_delete: delete_info: %s', delete_info,
                  instance=instance)

        if delete_info['type'] != 'qcow2':
            msg = _('Unknown delete_info type %s') % delete_info['type']
            raise exception.InternalError(msg)

        try:
            guest = self._host.get_guest(instance)
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)

        # Find dev name
        my_dev = None
        active_disk = None

        xml = guest.get_xml_desc()
        xml_doc = etree.fromstring(xml)

        device_info = vconfig.LibvirtConfigGuest()
        device_info.parse_dom(xml_doc)

        active_disk_object = None

        for guest_disk in device_info.devices:
            if (guest_disk.root_name != 'disk'):
                continue

            if (guest_disk.target_dev is None or guest_disk.serial is None):
                continue

            if guest_disk.serial == volume_id:
                my_dev = guest_disk.target_dev

                active_disk = guest_disk.source_path
                active_protocol = guest_disk.source_protocol
                active_disk_object = guest_disk
                break

        if my_dev is None or (active_disk is None and active_protocol is None):
            LOG.debug('Domain XML: %s', xml, instance=instance)
            msg = (_('Disk with id: %s not found attached to instance.')
                   % volume_id)
            raise exception.InternalError(msg)

        LOG.debug("found device at %s", my_dev, instance=instance)

        def _get_snap_dev(filename, backing_store):
            if filename is None:
                msg = _('filename cannot be None')
                raise exception.InternalError(msg)

            # libgfapi delete
            LOG.debug("XML: %s", xml)

            LOG.debug("active disk object: %s", active_disk_object)

            # determine reference within backing store for desired image
            filename_to_merge = filename
            matched_name = None
            b = backing_store
            index = None

            current_filename = active_disk_object.source_name.split('/')[1]
            if current_filename == filename_to_merge:
                return my_dev + '[0]'

            while b is not None:
                source_filename = b.source_name.split('/')[1]
                if source_filename == filename_to_merge:
                    LOG.debug('found match: %s', b.source_name)
                    matched_name = b.source_name
                    index = b.index
                    break

                b = b.backing_store

            if matched_name is None:
                msg = _('no match found for %s') % (filename_to_merge)
                raise exception.InternalError(msg)

            LOG.debug('index of match (%s) is %s', b.source_name, index)

            my_snap_dev = '%s[%s]' % (my_dev, index)
            return my_snap_dev

        if delete_info['merge_target_file'] is None:
            # pull via blockRebase()

            # Merge the most recent snapshot into the active image

            rebase_disk = my_dev
            rebase_base = delete_info['file_to_merge']  # often None
            if (active_protocol is not None) and (rebase_base is not None):
                rebase_base = _get_snap_dev(rebase_base,
                                            active_disk_object.backing_store)

            # NOTE(deepakcs): libvirt added support for _RELATIVE in v1.2.7,
            # and when available this flag _must_ be used to ensure backing
            # paths are maintained relative by qemu.
            #
            # If _RELATIVE flag not found, continue with old behaviour
            # (relative backing path seems to work for this case)
            try:
                libvirt.VIR_DOMAIN_BLOCK_REBASE_RELATIVE
                relative = rebase_base is not None
            except AttributeError:
                LOG.warning(
                    "Relative blockrebase support was not detected. "
                    "Continuing with old behaviour.")
                relative = False

            LOG.debug(
                'disk: %(disk)s, base: %(base)s, '
                'bw: %(bw)s, relative: %(relative)s',
                {'disk': rebase_disk,
                 'base': rebase_base,
                 'bw': libvirt_guest.BlockDevice.REBASE_DEFAULT_BANDWIDTH,
                 'relative': str(relative)}, instance=instance)

            dev = guest.get_block_device(rebase_disk)
            if guest.is_active():
                result = dev.rebase(rebase_base, relative=relative)
                if result == 0:
                    LOG.debug('blockRebase started successfully',
                              instance=instance)

                while not dev.is_job_complete():
                    LOG.debug('waiting for blockRebase job completion',
                              instance=instance)
                    time.sleep(0.5)

            # If the guest is not running libvirt won't do a blockRebase.
            # In that case, let's ask qemu-img to rebase the disk.
            else:
                LOG.debug('Guest is not running so doing a block rebase '
                          'using "qemu-img rebase"', instance=instance)
                self._rebase_with_qemu_img(guest, dev, active_disk_object,
                                           rebase_base)

        else:
            # commit with blockCommit()
            my_snap_base = None
            my_snap_top = None
            commit_disk = my_dev

            if active_protocol is not None:
                my_snap_base = _get_snap_dev(delete_info['merge_target_file'],
                                             active_disk_object.backing_store)
                my_snap_top = _get_snap_dev(delete_info['file_to_merge'],
                                            active_disk_object.backing_store)

            commit_base = my_snap_base or delete_info['merge_target_file']
            commit_top = my_snap_top or delete_info['file_to_merge']

            LOG.debug('will call blockCommit with commit_disk=%(commit_disk)s '
                      'commit_base=%(commit_base)s '
                      'commit_top=%(commit_top)s ',
                      {'commit_disk': commit_disk,
                       'commit_base': commit_base,
                       'commit_top': commit_top}, instance=instance)

            dev = guest.get_block_device(commit_disk)
            result = dev.commit(commit_base, commit_top, relative=True)

            if result == 0:
                LOG.debug('blockCommit started successfully',
                          instance=instance)

            while not dev.is_job_complete():
                LOG.debug('waiting for blockCommit job completion',
                          instance=instance)
                time.sleep(0.5)

    def volume_snapshot_delete(self, context, instance, volume_id, snapshot_id,
                               delete_info):
        try:
            self._volume_snapshot_delete(context, instance, volume_id,
                                         snapshot_id, delete_info=delete_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_('Error occurred during '
                                'volume_snapshot_delete, '
                                'sending error status to Cinder.'),
                              instance=instance)
                self._volume_snapshot_update_status(
                    context, snapshot_id, 'error_deleting')

        self._volume_snapshot_update_status(context, snapshot_id, 'deleting')
        self._volume_refresh_connection_info(context, instance, volume_id)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot a virtual machine, given an instance reference."""
        if reboot_type == 'SOFT':
            # NOTE(vish): This will attempt to do a graceful shutdown/restart.
            try:
                soft_reboot_success = self._soft_reboot(instance)
            except libvirt.libvirtError as e:
                LOG.debug("Instance soft reboot failed: %s", e,
                          instance=instance)
                soft_reboot_success = False

            if soft_reboot_success:
                LOG.info("Instance soft rebooted successfully.",
                         instance=instance)
                return
            else:
                LOG.warning("Failed to soft reboot instance. "
                            "Trying hard reboot.",
                            instance=instance)
        return self._hard_reboot(context, instance, network_info,
                                 block_device_info)

    def _soft_reboot(self, instance):
        """Attempt to shutdown and restart the instance gracefully.

        We use shutdown and create here so we can return if the guest
        responded and actually rebooted. Note that this method only
        succeeds if the guest responds to acpi. Therefore we return
        success or failure so we can fall back to a hard reboot if
        necessary.

        :returns: True if the reboot succeeded
        """
        guest = self._host.get_guest(instance)

        state = guest.get_power_state(self._host)
        old_domid = guest.id
        # NOTE(vish): This check allows us to reboot an instance that
        #             is already shutdown.
        if state == power_state.RUNNING:
            guest.shutdown()
        # NOTE(vish): This actually could take slightly longer than the
        #             FLAG defines depending on how long the get_info
        #             call takes to return.
        self._prepare_pci_devices_for_use(
            pci_manager.get_instance_pci_devs(instance, 'all'))
        for x in range(CONF.libvirt.wait_soft_reboot_seconds):
            guest = self._host.get_guest(instance)

            state = guest.get_power_state(self._host)
            new_domid = guest.id

            # NOTE(ivoks): By checking domain IDs, we make sure we are
            #              not recreating domain that's already running.
            if old_domid != new_domid:
                if state in [power_state.SHUTDOWN,
                             power_state.CRASHED]:
                    LOG.info("Instance shutdown successfully.",
                             instance=instance)
                    self._create_domain(domain=guest._domain)
                    timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_running, instance)
                    timer.start(interval=0.5).wait()
                    return True
                else:
                    LOG.info("Instance may have been rebooted during soft "
                             "reboot, so return now.", instance=instance)
                    return True
            greenthread.sleep(1)
        return False

    def _hard_reboot(self, context, instance, network_info,
                     block_device_info=None):
        """Reboot a virtual machine, given an instance reference.

        Performs a Libvirt reset (if supported) on the domain.

        If Libvirt reset is unavailable this method actually destroys and
        re-creates the domain to ensure the reboot happens, as the guest
        OS cannot ignore this action.
        """
        # NOTE(mdbooth): In addition to performing a hard reboot of the domain,
        # the hard reboot operation is relied upon by operators to be an
        # automated attempt to fix as many things as possible about a
        # non-functioning instance before resorting to manual intervention.
        # With this goal in mind, we tear down all the aspects of an instance
        # we can here without losing data. This allows us to re-initialise from
        # scratch, and hopefully fix, most aspects of a non-functioning guest.
        self.destroy(context, instance, network_info, destroy_disks=False,
                     block_device_info=block_device_info)

        # Convert the system metadata to image metadata
        # NOTE(mdbooth): This is a workaround for stateless Nova compute
        #                https://bugs.launchpad.net/nova/+bug/1349978
        instance_dir = libvirt_utils.get_instance_path(instance)
        fileutils.ensure_tree(instance_dir)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            instance.image_meta,
                                            block_device_info)
        # NOTE(vish): This could generate the wrong device_format if we are
        #             using the raw backend and the images don't exist yet.
        #             The create_images_and_backing below doesn't properly
        #             regenerate raw backend images, however, so when it
        #             does we need to (re)generate the xml after the images
        #             are in place.
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  instance.image_meta,
                                  block_device_info=block_device_info)

        # NOTE(mdbooth): context.auth_token will not be set when we call
        #                _hard_reboot from resume_state_on_host_boot()
        if context.auth_token is not None:
            # NOTE (rmk): Re-populate any missing backing files.
            config = vconfig.LibvirtConfigGuest()
            config.parse_str(xml)
            backing_disk_info = self._get_instance_disk_info_from_config(
                config, block_device_info)
            self._create_images_and_backing(context, instance, instance_dir,
                                            backing_disk_info)

        # Initialize all the necessary networking, block devices and
        # start the instance.
        # NOTE(melwitt): Pass vifs_already_plugged=True here even though we've
        # unplugged vifs earlier. The behavior of neutron plug events depends
        # on which vif type we're using and we are working with a stale network
        # info cache here, so won't rely on waiting for neutron plug events.
        # vifs_already_plugged=True means "do not wait for neutron plug events"
        self._create_domain_and_network(context, xml, instance, network_info,
                                        block_device_info=block_device_info,
                                        vifs_already_plugged=True)
        self._prepare_pci_devices_for_use(
            pci_manager.get_instance_pci_devs(instance, 'all'))

        def _wait_for_reboot():
            """Called at an interval until the VM is running again."""
            state = self.get_info(instance).state

            if state == power_state.RUNNING:
                LOG.info("Instance rebooted successfully.",
                         instance=instance)
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot)
        timer.start(interval=0.5).wait()

    def pause(self, instance):
        """Pause VM instance."""
        self._host.get_guest(instance).pause()

    def unpause(self, instance):
        """Unpause paused VM instance."""
        guest = self._host.get_guest(instance)
        guest.resume()
        guest.sync_guest_time()

    def _clean_shutdown(self, instance, timeout, retry_interval):
        """Attempt to shutdown the instance gracefully.

        :param instance: The instance to be shutdown
        :param timeout: How long to wait in seconds for the instance to
                        shutdown
        :param retry_interval: How often in seconds to signal the instance
                               to shutdown while waiting

        :returns: True if the shutdown succeeded
        """

        # List of states that represent a shutdown instance
        SHUTDOWN_STATES = [power_state.SHUTDOWN,
                           power_state.CRASHED]

        try:
            guest = self._host.get_guest(instance)
        except exception.InstanceNotFound:
            # If the instance has gone then we don't need to
            # wait for it to shutdown
            return True

        state = guest.get_power_state(self._host)
        if state in SHUTDOWN_STATES:
            LOG.info("Instance already shutdown.", instance=instance)
            return True

        LOG.debug("Shutting down instance from state %s", state,
                  instance=instance)
        guest.shutdown()
        retry_countdown = retry_interval

        for sec in range(timeout):

            guest = self._host.get_guest(instance)
            state = guest.get_power_state(self._host)

            if state in SHUTDOWN_STATES:
                LOG.info("Instance shutdown successfully after %d seconds.",
                         sec, instance=instance)
                return True

            # Note(PhilD): We can't assume that the Guest was able to process
            #              any previous shutdown signal (for example it may
            #              have still been startingup, so within the overall
            #              timeout we re-trigger the shutdown every
            #              retry_interval
            if retry_countdown == 0:
                retry_countdown = retry_interval
                # Instance could shutdown at any time, in which case we
                # will get an exception when we call shutdown
                try:
                    LOG.debug("Instance in state %s after %d seconds - "
                              "resending shutdown", state, sec,
                              instance=instance)
                    guest.shutdown()
                except libvirt.libvirtError:
                    # Assume this is because its now shutdown, so loop
                    # one more time to clean up.
                    LOG.debug("Ignoring libvirt exception from shutdown "
                              "request.", instance=instance)
                    continue
            else:
                retry_countdown -= 1

            time.sleep(1)

        LOG.info("Instance failed to shutdown in %d seconds.",
                 timeout, instance=instance)
        return False

    def power_off(self, instance, timeout=0, retry_interval=0):
        """Power off the specified instance."""
        if timeout:
            self._clean_shutdown(instance, timeout, retry_interval)
        self._destroy(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        # We use _hard_reboot here to ensure that all backing files,
        # network, and block device connections, etc. are established
        # and available before we attempt to start the instance.
        self._hard_reboot(context, instance, network_info, block_device_info)

    def trigger_crash_dump(self, instance):

        """Trigger crash dump by injecting an NMI to the specified instance."""
        try:
            self._host.get_guest(instance).inject_nmi()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()

            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                raise exception.TriggerCrashDumpNotSupported()
            elif error_code == libvirt.VIR_ERR_OPERATION_INVALID:
                raise exception.InstanceNotRunning(instance_id=instance.uuid)

            LOG.exception(_('Error from libvirt while injecting an NMI to '
                            '%(instance_uuid)s: '
                            '[Error Code %(error_code)s] %(ex)s'),
                          {'instance_uuid': instance.uuid,
                           'error_code': error_code, 'ex': ex})
            raise

    def suspend(self, context, instance):
        """Suspend the specified instance."""
        guest = self._host.get_guest(instance)

        self._detach_pci_devices(guest,
            pci_manager.get_instance_pci_devs(instance))
        self._detach_direct_passthrough_ports(context, instance, guest)
        guest.save_memory_state()

    def resume(self, context, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        xml = self._get_existing_domain_xml(instance, network_info,
                                            block_device_info)
        guest = self._create_domain_and_network(context, xml, instance,
                           network_info, block_device_info=block_device_info,
                           vifs_already_plugged=True)
        self._attach_pci_devices(guest,
            pci_manager.get_instance_pci_devs(instance))
        self._attach_direct_passthrough_ports(
            context, instance, guest, network_info)
        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_running,
                                                     instance)
        timer.start(interval=0.5).wait()
        guest.sync_guest_time()

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        # Check if the instance is running already and avoid doing
        # anything if it is.
        try:
            guest = self._host.get_guest(instance)
            state = guest.get_power_state(self._host)

            ignored_states = (power_state.RUNNING,
                              power_state.SUSPENDED,
                              power_state.NOSTATE,
                              power_state.PAUSED)

            if state in ignored_states:
                return
        except (exception.InternalError, exception.InstanceNotFound):
            pass

        # Instance is not up and could be in an unknown state.
        # Be as absolute as possible about getting it back into
        # a known and running state.
        self._hard_reboot(context, instance, network_info, block_device_info)

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        """Loads a VM using rescue images.

        A rescue is normally performed when something goes wrong with the
        primary images and data needs to be corrected/recovered. Rescuing
        should not edit or over-ride the original image, only allow for
        data recovery.

        """
        instance_dir = libvirt_utils.get_instance_path(instance)
        unrescue_xml = self._get_existing_domain_xml(instance, network_info)
        unrescue_xml_path = os.path.join(instance_dir, 'unrescue.xml')
        libvirt_utils.write_to_file(unrescue_xml_path, unrescue_xml)

        rescue_image_id = None
        if image_meta.obj_attr_is_set("id"):
            rescue_image_id = image_meta.id

        rescue_images = {
            'image_id': (rescue_image_id or
                        CONF.libvirt.rescue_image_id or instance.image_ref),
            'kernel_id': (CONF.libvirt.rescue_kernel_id or
                          instance.kernel_id),
            'ramdisk_id': (CONF.libvirt.rescue_ramdisk_id or
                           instance.ramdisk_id),
        }
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            image_meta,
                                            rescue=True)
        injection_info = InjectionInfo(network_info=network_info,
                                       admin_pass=rescue_password,
                                       files=None)
        gen_confdrive = functools.partial(self._create_configdrive,
                                          context, instance, injection_info,
                                          rescue=True)
        self._create_image(context, instance, disk_info['mapping'],
                           injection_info=injection_info, suffix='.rescue',
                           disk_images=rescue_images)
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  image_meta, rescue=rescue_images)
        self._destroy(instance)
        self._create_domain(xml, post_xml_callback=gen_confdrive)

    def unrescue(self, instance, network_info):
        """Reboot the VM which is being rescued back into primary images.
        """
        instance_dir = libvirt_utils.get_instance_path(instance)
        unrescue_xml_path = os.path.join(instance_dir, 'unrescue.xml')
        xml = libvirt_utils.load_file(unrescue_xml_path)
        guest = self._host.get_guest(instance)

        # TODO(sahid): We are converting all calls from a
        # virDomain object to use nova.virt.libvirt.Guest.
        # We should be able to remove virt_dom at the end.
        virt_dom = guest._domain
        self._destroy(instance)
        self._create_domain(xml, virt_dom)
        libvirt_utils.file_delete(unrescue_xml_path)
        rescue_files = os.path.join(instance_dir, "*.rescue")
        for rescue_file in glob.iglob(rescue_files):
            if os.path.isdir(rescue_file):
                shutil.rmtree(rescue_file)
            else:
                libvirt_utils.file_delete(rescue_file)
        # cleanup rescue volume
        lvm.remove_volumes([lvmdisk for lvmdisk in self._lvm_disks(instance)
                                if lvmdisk.endswith('.rescue')])
        if CONF.libvirt.images_type == 'rbd':
            filter_fn = lambda disk: (disk.startswith(instance.uuid) and
                                      disk.endswith('.rescue'))
            LibvirtDriver._get_rbd_driver().cleanup_volumes(filter_fn)

    def poll_rebooting_instances(self, timeout, instances):
        pass

    # NOTE(ilyaalekseyev): Implementation like in multinics
    # for xenapi(tr3buchet)
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            image_meta,
                                            block_device_info)
        injection_info = InjectionInfo(network_info=network_info,
                                       files=injected_files,
                                       admin_pass=admin_password)
        gen_confdrive = functools.partial(self._create_configdrive,
                                          context, instance,
                                          injection_info)
        self._create_image(context, instance, disk_info['mapping'],
                           injection_info=injection_info,
                           block_device_info=block_device_info)

        # Required by Quobyte CI
        self._ensure_console_log_for_instance(instance)

        xml = self._get_guest_xml(context, instance, network_info,
                                  disk_info, image_meta,
                                  block_device_info=block_device_info)
        self._create_domain_and_network(
            context, xml, instance, network_info,
            block_device_info=block_device_info,
            post_xml_callback=gen_confdrive,
            destroy_disks_on_failure=True)
        LOG.debug("Instance is running", instance=instance)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            state = self.get_info(instance).state

            if state == power_state.RUNNING:
                LOG.info("Instance spawned successfully.", instance=instance)
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_boot)
        timer.start(interval=0.5).wait()

    def _flush_libvirt_console(self, pty):
        out, err = utils.execute('dd',
                                 'if=%s' % pty,
                                 'iflag=nonblock',
                                 run_as_root=True,
                                 check_exit_code=False)
        return out

    def _append_to_file(self, data, fpath):
        LOG.info('data: %(data)r, fpath: %(fpath)r',
                 {'data': data, 'fpath': fpath})
        with open(fpath, 'a+') as fp:
            fp.write(data)

        return fpath

    def _get_console_output_file(self, instance, console_log):
        bytes_to_read = MAX_CONSOLE_BYTES
        log_data = b""  # The last N read bytes
        i = 0  # in case there is a log rotation (like "virtlogd")
        path = console_log
        while bytes_to_read > 0 and os.path.exists(path):
            libvirt_utils.chown(path, os.getuid())
            with libvirt_utils.file_open(path, 'rb') as fp:
                read_log_data, remaining = libvirt_utils.last_bytes(
                                                fp, bytes_to_read)
                # We need the log file content in chronological order,
                # that's why we *prepend* the log data.
                log_data = read_log_data + log_data
                bytes_to_read -= len(read_log_data)
                path = console_log + "." + str(i)
                i += 1
            if remaining > 0:
                LOG.info('Truncated console log returned, '
                         '%d bytes ignored', remaining, instance=instance)
        return log_data

    def get_console_output(self, context, instance):
        guest = self._host.get_guest(instance)

        xml = guest.get_xml_desc()
        tree = etree.fromstring(xml)

        # If the guest has a console logging to a file prefer to use that
        file_consoles = tree.findall("./devices/console[@type='file']")
        if file_consoles:
            for file_console in file_consoles:
                source_node = file_console.find('./source')
                if source_node is None:
                    continue
                path = source_node.get("path")
                if not path:
                    continue

                if not os.path.exists(path):
                    LOG.info('Instance is configured with a file console, '
                             'but the backing file is not (yet?) present',
                             instance=instance)
                    return ""

                return self._get_console_output_file(instance, path)

        # Try 'pty' types
        pty_consoles = tree.findall("./devices/console[@type='pty']")
        if pty_consoles:
            for pty_console in pty_consoles:
                source_node = pty_console.find('./source')
                if source_node is None:
                    continue
                pty = source_node.get("path")
                if not pty:
                    continue
                break
            else:
                raise exception.ConsoleNotAvailable()
        else:
            raise exception.ConsoleNotAvailable()

        console_log = self._get_console_log_path(instance)
        # By default libvirt chowns the console log when it starts a domain.
        # We need to chown it back before attempting to read from or write
        # to it.
        if os.path.exists(console_log):
            libvirt_utils.chown(console_log, os.getuid())

        data = self._flush_libvirt_console(pty)
        # NOTE(markus_z): The virt_types kvm and qemu are the only ones
        # which create a dedicated file device for the console logging.
        # Other virt_types like xen, lxc, uml, parallels depend on the
        # flush of that pty device into the "console.log" file to ensure
        # that a series of "get_console_output" calls return the complete
        # content even after rebooting a guest.
        fpath = self._append_to_file(data, console_log)

        return self._get_console_output_file(instance, fpath)

    def get_host_ip_addr(self):
        ips = compute_utils.get_machine_ips()
        if CONF.my_ip not in ips:
            LOG.warning('my_ip address (%(my_ip)s) was not found on '
                        'any of the interfaces: %(ifaces)s',
                        {'my_ip': CONF.my_ip, 'ifaces': ", ".join(ips)})
        return CONF.my_ip

    def get_vnc_console(self, context, instance):
        def get_vnc_port_for_instance(instance_name):
            guest = self._host.get_guest(instance)

            xml = guest.get_xml_desc()
            xml_dom = etree.fromstring(xml)

            graphic = xml_dom.find("./devices/graphics[@type='vnc']")
            if graphic is not None:
                return graphic.get('port')
            # NOTE(rmk): We had VNC consoles enabled but the instance in
            # question is not actually listening for connections.
            raise exception.ConsoleTypeUnavailable(console_type='vnc')

        port = get_vnc_port_for_instance(instance.name)
        host = CONF.vnc.vncserver_proxyclient_address

        return ctype.ConsoleVNC(host=host, port=port)

    def get_spice_console(self, context, instance):
        def get_spice_ports_for_instance(instance_name):
            guest = self._host.get_guest(instance)

            xml = guest.get_xml_desc()
            xml_dom = etree.fromstring(xml)

            graphic = xml_dom.find("./devices/graphics[@type='spice']")
            if graphic is not None:
                return (graphic.get('port'), graphic.get('tlsPort'))
            # NOTE(rmk): We had Spice consoles enabled but the instance in
            # question is not actually listening for connections.
            raise exception.ConsoleTypeUnavailable(console_type='spice')

        ports = get_spice_ports_for_instance(instance.name)
        host = CONF.spice.server_proxyclient_address

        return ctype.ConsoleSpice(host=host, port=ports[0], tlsPort=ports[1])

    def get_serial_console(self, context, instance):
        guest = self._host.get_guest(instance)
        for hostname, port in self._get_serial_ports_from_guest(
                guest, mode='bind'):
            return ctype.ConsoleSerial(host=hostname, port=port)
        raise exception.ConsoleTypeUnavailable(console_type='serial')

    @staticmethod
    def _supports_direct_io(dirpath):

        if not hasattr(os, 'O_DIRECT'):
            LOG.debug("This python runtime does not support direct I/O")
            return False

        testfile = os.path.join(dirpath, ".directio.test")

        hasDirectIO = True
        fd = None
        try:
            fd = os.open(testfile, os.O_CREAT | os.O_WRONLY | os.O_DIRECT)
            # Check is the write allowed with 4096 byte alignment
            align_size = 4096
            m = mmap.mmap(-1, align_size)
            m.write(b"x" * align_size)
            os.write(fd, m)
            LOG.debug("Path '%(path)s' supports direct I/O",
                      {'path': dirpath})
        except OSError as e:
            if e.errno == errno.EINVAL:
                LOG.debug("Path '%(path)s' does not support direct I/O: "
                          "'%(ex)s'", {'path': dirpath, 'ex': e})
                hasDirectIO = False
            else:
                with excutils.save_and_reraise_exception():
                    LOG.error("Error on '%(path)s' while checking "
                              "direct I/O: '%(ex)s'",
                              {'path': dirpath, 'ex': e})
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Error on '%(path)s' while checking direct I/O: "
                          "'%(ex)s'", {'path': dirpath, 'ex': e})
        finally:
            # ensure unlink(filepath) will actually remove the file by deleting
            # the remaining link to it in close(fd)
            if fd is not None:
                os.close(fd)

            try:
                os.unlink(testfile)
            except Exception:
                pass

        return hasDirectIO

    @staticmethod
    def _create_ephemeral(target, ephemeral_size,
                          fs_label, os_type, is_block_dev=False,
                          context=None, specified_fs=None,
                          vm_mode=None):
        if not is_block_dev:
            if (CONF.libvirt.virt_type == "parallels" and
                    vm_mode == fields.VMMode.EXE):

                libvirt_utils.create_ploop_image('expanded', target,
                                                 '%dG' % ephemeral_size,
                                                 specified_fs)
                return
            libvirt_utils.create_image('raw', target, '%dG' % ephemeral_size)

        # Run as root only for block devices.
        disk_api.mkfs(os_type, fs_label, target, run_as_root=is_block_dev,
                      specified_fs=specified_fs)

    @staticmethod
    def _create_swap(target, swap_mb, context=None):
        """Create a swap file of specified size."""
        libvirt_utils.create_image('raw', target, '%dM' % swap_mb)
        utils.mkfs('swap', target)

    @staticmethod
    def _get_console_log_path(instance):
        return os.path.join(libvirt_utils.get_instance_path(instance),
                            'console.log')

    def _ensure_console_log_for_instance(self, instance):
        # NOTE(mdbooth): Although libvirt will create this file for us
        # automatically when it starts, it will initially create it with
        # root ownership and then chown it depending on the configuration of
        # the domain it is launching. Quobyte CI explicitly disables the
        # chown by setting dynamic_ownership=0 in libvirt's config.
        # Consequently when the domain starts it is unable to write to its
        # console.log. See bug https://bugs.launchpad.net/nova/+bug/1597644
        #
        # To work around this, we create the file manually before starting
        # the domain so it has the same ownership as Nova. This works
        # for Quobyte CI because it is also configured to run qemu as the same
        # user as the Nova service. Installations which don't set
        # dynamic_ownership=0 are not affected because libvirt will always
        # correctly configure permissions regardless of initial ownership.
        #
        # Setting dynamic_ownership=0 is dubious and potentially broken in
        # more ways than console.log (see comment #22 on the above bug), so
        # Future Maintainer who finds this code problematic should check to see
        # if we still support it.
        console_file = self._get_console_log_path(instance)
        LOG.debug('Ensure instance console log exists: %s', console_file,
                  instance=instance)
        try:
            libvirt_utils.file_open(console_file, 'a').close()
        # NOTE(sfinucan): We can safely ignore permission issues here and
        # assume that it is libvirt that has taken ownership of this file.
        except IOError as ex:
            if ex.errno != errno.EACCES:
                raise
            LOG.debug('Console file already exists: %s.', console_file)

    @staticmethod
    def _get_disk_config_image_type():
        # TODO(mikal): there is a bug here if images_type has
        # changed since creation of the instance, but I am pretty
        # sure that this bug already exists.
        return 'rbd' if CONF.libvirt.images_type == 'rbd' else 'raw'

    @staticmethod
    def _is_booted_from_volume(block_device_info):
        """Determines whether the VM is booting from volume

        Determines whether the block device info indicates that the VM
        is booting from a volume.
        """
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        return bool(block_device.get_root_bdm(block_device_mapping))

    def _inject_data(self, disk, instance, injection_info):
        """Injects data in a disk image

        Helper used for injecting data in a disk image file system.

        :param disk: The disk we're injecting into (an Image object)
        :param instance: The instance we're injecting into
        :param injection_info: Injection info
        """
        # Handles the partition need to be used.
        LOG.debug('Checking root disk injection %s',
                  str(injection_info), instance=instance)
        target_partition = None
        if not instance.kernel_id:
            target_partition = CONF.libvirt.inject_partition
            if target_partition == 0:
                target_partition = None
        if CONF.libvirt.virt_type == 'lxc':
            target_partition = None

        # Handles the key injection.
        if CONF.libvirt.inject_key and instance.get('key_data'):
            key = str(instance.key_data)
        else:
            key = None

        # Handles the admin password injection.
        if not CONF.libvirt.inject_password:
            admin_pass = None
        else:
            admin_pass = injection_info.admin_pass

        # Handles the network injection.
        net = netutils.get_injected_network_template(
            injection_info.network_info,
            libvirt_virt_type=CONF.libvirt.virt_type)

        # Handles the metadata injection
        metadata = instance.get('metadata')

        if any((key, net, metadata, admin_pass, injection_info.files)):
            LOG.debug('Injecting %s', str(injection_info),
                      instance=instance)
            img_id = instance.image_ref
            try:
                disk_api.inject_data(disk.get_model(self._conn),
                                     key, net, metadata, admin_pass,
                                     injection_info.files,
                                     partition=target_partition,
                                     mandatory=('files',))
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    LOG.error('Error injecting data into image '
                              '%(img_id)s (%(e)s)',
                              {'img_id': img_id, 'e': e},
                              instance=instance)

    # NOTE(sileht): many callers of this method assume that this
    # method doesn't fail if an image already exists but instead
    # think that it will be reused (ie: (live)-migration/resize)
    def _create_image(self, context, instance,
                      disk_mapping, injection_info=None, suffix='',
                      disk_images=None, block_device_info=None,
                      fallback_from_host=None,
                      ignore_bdi_for_swap=False):
        booted_from_volume = self._is_booted_from_volume(block_device_info)

        def image(fname, image_type=CONF.libvirt.images_type):
            return self.image_backend.by_name(instance,
                                              fname + suffix, image_type)

        def raw(fname):
            return image(fname, image_type='raw')

        # ensure directories exist and are writable
        fileutils.ensure_tree(libvirt_utils.get_instance_path(instance))

        LOG.info('Creating image', instance=instance)

        inst_type = instance.get_flavor()
        swap_mb = 0
        if 'disk.swap' in disk_mapping:
            mapping = disk_mapping['disk.swap']

            if ignore_bdi_for_swap:
                # This is a workaround to support legacy swap resizing,
                # which does not touch swap size specified in bdm,
                # but works with flavor specified size only.
                # In this case we follow the legacy logic and ignore block
                # device info completely.
                # NOTE(ft): This workaround must be removed when a correct
                # implementation of resize operation changing sizes in bdms is
                # developed. Also at that stage we probably may get rid of
                # the direct usage of flavor swap size here,
                # leaving the work with bdm only.
                swap_mb = inst_type['swap']
            else:
                swap = driver.block_device_info_get_swap(block_device_info)
                if driver.swap_is_usable(swap):
                    swap_mb = swap['swap_size']
                elif (inst_type['swap'] > 0 and
                      not block_device.volume_in_mapping(
                        mapping['dev'], block_device_info)):
                    swap_mb = inst_type['swap']

            if swap_mb > 0:
                if (CONF.libvirt.virt_type == "parallels" and
                        instance.vm_mode == fields.VMMode.EXE):
                    msg = _("Swap disk is not supported "
                            "for Virtuozzo container")
                    raise exception.Invalid(msg)

        if not disk_images:
            disk_images = {'image_id': instance.image_ref,
                           'kernel_id': instance.kernel_id,
                           'ramdisk_id': instance.ramdisk_id}

        if disk_images['kernel_id']:
            fname = imagecache.get_cache_fname(disk_images['kernel_id'])
            raw('kernel').cache(fetch_func=libvirt_utils.fetch_raw_image,
                                context=context,
                                filename=fname,
                                image_id=disk_images['kernel_id'])
            if disk_images['ramdisk_id']:
                fname = imagecache.get_cache_fname(disk_images['ramdisk_id'])
                raw('ramdisk').cache(fetch_func=libvirt_utils.fetch_raw_image,
                                     context=context,
                                     filename=fname,
                                     image_id=disk_images['ramdisk_id'])

        if CONF.libvirt.virt_type == 'uml':
            libvirt_utils.chown(image('disk').path, 'root')

        self._create_and_inject_local_root(context, instance,
                                           booted_from_volume, suffix,
                                           disk_images, injection_info,
                                           fallback_from_host)

        # Lookup the filesystem type if required
        os_type_with_default = disk_api.get_fs_type_for_os_type(
            instance.os_type)
        # Generate a file extension based on the file system
        # type and the mkfs commands configured if any
        file_extension = disk_api.get_file_extension_for_os_type(
                                                          os_type_with_default)

        vm_mode = fields.VMMode.get_from_instance(instance)
        ephemeral_gb = instance.flavor.ephemeral_gb
        if 'disk.local' in disk_mapping:
            disk_image = image('disk.local')
            fn = functools.partial(self._create_ephemeral,
                                   fs_label='ephemeral0',
                                   os_type=instance.os_type,
                                   is_block_dev=disk_image.is_block_dev,
                                   vm_mode=vm_mode)
            fname = "ephemeral_%s_%s" % (ephemeral_gb, file_extension)
            size = ephemeral_gb * units.Gi
            disk_image.cache(fetch_func=fn,
                             context=context,
                             filename=fname,
                             size=size,
                             ephemeral_size=ephemeral_gb)

        for idx, eph in enumerate(driver.block_device_info_get_ephemerals(
                block_device_info)):
            disk_image = image(blockinfo.get_eph_disk(idx))

            specified_fs = eph.get('guest_format')
            if specified_fs and not self.is_supported_fs_format(specified_fs):
                msg = _("%s format is not supported") % specified_fs
                raise exception.InvalidBDMFormat(details=msg)

            fn = functools.partial(self._create_ephemeral,
                                   fs_label='ephemeral%d' % idx,
                                   os_type=instance.os_type,
                                   is_block_dev=disk_image.is_block_dev,
                                   vm_mode=vm_mode)
            size = eph['size'] * units.Gi
            fname = "ephemeral_%s_%s" % (eph['size'], file_extension)
            disk_image.cache(fetch_func=fn,
                             context=context,
                             filename=fname,
                             size=size,
                             ephemeral_size=eph['size'],
                             specified_fs=specified_fs)

        if swap_mb > 0:
            size = swap_mb * units.Mi
            image('disk.swap').cache(fetch_func=self._create_swap,
                                     context=context,
                                     filename="swap_%s" % swap_mb,
                                     size=size,
                                     swap_mb=swap_mb)

    def _create_and_inject_local_root(self, context, instance,
                                      booted_from_volume, suffix, disk_images,
                                      injection_info, fallback_from_host):
        # File injection only if needed
        need_inject = (not configdrive.required_by(instance) and
                       injection_info is not None and
                       CONF.libvirt.inject_partition != -2)

        # NOTE(ndipanov): Even if disk_mapping was passed in, which
        # currently happens only on rescue - we still don't want to
        # create a base image.
        if not booted_from_volume:
            root_fname = imagecache.get_cache_fname(disk_images['image_id'])
            size = instance.flavor.root_gb * units.Gi

            if size == 0 or suffix == '.rescue':
                size = None

            backend = self.image_backend.by_name(instance, 'disk' + suffix,
                                                 CONF.libvirt.images_type)
            if instance.task_state == task_states.RESIZE_FINISH:
                backend.create_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)
            if backend.SUPPORTS_CLONE:
                def clone_fallback_to_fetch(*args, **kwargs):
                    try:
                        backend.clone(context, disk_images['image_id'])
                    except exception.ImageUnacceptable:
                        libvirt_utils.fetch_image(*args, **kwargs)
                fetch_func = clone_fallback_to_fetch
            else:
                fetch_func = libvirt_utils.fetch_image
            self._try_fetch_image_cache(backend, fetch_func, context,
                                        root_fname, disk_images['image_id'],
                                        instance, size, fallback_from_host)

            if need_inject:
                self._inject_data(backend, instance, injection_info)

        elif need_inject:
            LOG.warning('File injection into a boot from volume '
                        'instance is not supported', instance=instance)

    def _create_configdrive(self, context, instance, injection_info,
                            rescue=False):
        # As this method being called right after the definition of a
        # domain, but before its actual launch, device metadata will be built
        # and saved in the instance for it to be used by the config drive and
        # the metadata service.
        instance.device_metadata = self._build_device_metadata(context,
                                                               instance)
        if configdrive.required_by(instance):
            LOG.info('Using config drive', instance=instance)

            name = 'disk.config'
            if rescue:
                name += '.rescue'

            config_disk = self.image_backend.by_name(
                instance, name, self._get_disk_config_image_type())

            # Don't overwrite an existing config drive
            if not config_disk.exists():
                extra_md = {}
                if injection_info.admin_pass:
                    extra_md['admin_pass'] = injection_info.admin_pass

                inst_md = instance_metadata.InstanceMetadata(
                    instance, content=injection_info.files, extra_md=extra_md,
                    network_info=injection_info.network_info,
                    request_context=context)

                cdb = configdrive.ConfigDriveBuilder(instance_md=inst_md)
                with cdb:
                    # NOTE(mdbooth): We're hardcoding here the path of the
                    # config disk when using the flat backend. This isn't
                    # good, but it's required because we need a local path we
                    # know we can write to in case we're subsequently
                    # importing into rbd. This will be cleaned up when we
                    # replace this with a call to create_from_func, but that
                    # can't happen until we've updated the backends and we
                    # teach them not to cache config disks. This isn't
                    # possible while we're still using cache() under the hood.
                    config_disk_local_path = os.path.join(
                        libvirt_utils.get_instance_path(instance), name)
                    LOG.info('Creating config drive at %(path)s',
                             {'path': config_disk_local_path},
                             instance=instance)

                    try:
                        cdb.make_drive(config_disk_local_path)
                    except processutils.ProcessExecutionError as e:
                        with excutils.save_and_reraise_exception():
                            LOG.error('Creating config drive failed with '
                                      'error: %s', e, instance=instance)

                try:
                    config_disk.import_file(
                        instance, config_disk_local_path, name)
                finally:
                    # NOTE(mikal): if the config drive was imported into RBD,
                    # then we no longer need the local copy
                    if CONF.libvirt.images_type == 'rbd':
                        LOG.info('Deleting local config drive %(path)s '
                                 'because it was imported into RBD.',
                                 {'path': config_disk_local_path},
                                 instance=instance)
                        os.unlink(config_disk_local_path)

    def _prepare_pci_devices_for_use(self, pci_devices):
        # kvm , qemu support managed mode
        # In managed mode, the configured device will be automatically
        # detached from the host OS drivers when the guest is started,
        # and then re-attached when the guest shuts down.
        if CONF.libvirt.virt_type != 'xen':
            # we do manual detach only for xen
            return
        try:
            for dev in pci_devices:
                libvirt_dev_addr = dev['hypervisor_name']
                libvirt_dev = \
                        self._host.device_lookup_by_name(libvirt_dev_addr)
                # Note(yjiang5) Spelling for 'dettach' is correct, see
                # http://libvirt.org/html/libvirt-libvirt.html.
                libvirt_dev.dettach()

            # Note(yjiang5): A reset of one PCI device may impact other
            # devices on the same bus, thus we need two separated loops
            # to detach and then reset it.
            for dev in pci_devices:
                libvirt_dev_addr = dev['hypervisor_name']
                libvirt_dev = \
                        self._host.device_lookup_by_name(libvirt_dev_addr)
                libvirt_dev.reset()

        except libvirt.libvirtError as exc:
            raise exception.PciDevicePrepareFailed(id=dev['id'],
                                                   instance_uuid=
                                                   dev['instance_uuid'],
                                                   reason=six.text_type(exc))

    def _detach_pci_devices(self, guest, pci_devs):
        try:
            for dev in pci_devs:
                guest.detach_device(self._get_guest_pci_device(dev), live=True)
                # after detachDeviceFlags returned, we should check the dom to
                # ensure the detaching is finished
                xml = guest.get_xml_desc()
                xml_doc = etree.fromstring(xml)
                guest_config = vconfig.LibvirtConfigGuest()
                guest_config.parse_dom(xml_doc)

                for hdev in [d for d in guest_config.devices
                    if isinstance(d, vconfig.LibvirtConfigGuestHostdevPCI)]:
                    hdbsf = [hdev.domain, hdev.bus, hdev.slot, hdev.function]
                    dbsf = pci_utils.parse_address(dev.address)
                    if [int(x, 16) for x in hdbsf] ==\
                            [int(x, 16) for x in dbsf]:
                        raise exception.PciDeviceDetachFailed(reason=
                                                              "timeout",
                                                              dev=dev)

        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                LOG.warning("Instance disappeared while detaching "
                            "a PCI device from it.")
            else:
                raise

    def _attach_pci_devices(self, guest, pci_devs):
        try:
            for dev in pci_devs:
                guest.attach_device(self._get_guest_pci_device(dev))

        except libvirt.libvirtError:
            LOG.error('Attaching PCI devices %(dev)s to %(dom)s failed.',
                      {'dev': pci_devs, 'dom': guest.id})
            raise

    @staticmethod
    def _has_direct_passthrough_port(network_info):
        for vif in network_info:
            if (vif['vnic_type'] in
                network_model.VNIC_TYPES_DIRECT_PASSTHROUGH):
                return True
        return False

    def _attach_direct_passthrough_ports(
        self, context, instance, guest, network_info=None):
        if network_info is None:
            network_info = instance.info_cache.network_info
        if network_info is None:
            return

        if self._has_direct_passthrough_port(network_info):
            for vif in network_info:
                if (vif['vnic_type'] in
                    network_model.VNIC_TYPES_DIRECT_PASSTHROUGH):
                    cfg = self.vif_driver.get_config(instance,
                                                     vif,
                                                     instance.image_meta,
                                                     instance.flavor,
                                                     CONF.libvirt.virt_type,
                                                     self._host)
                    LOG.debug('Attaching direct passthrough port %(port)s '
                              'to %(dom)s', {'port': vif, 'dom': guest.id},
                              instance=instance)
                    guest.attach_device(cfg)

    def _detach_direct_passthrough_ports(self, context, instance, guest):
        network_info = instance.info_cache.network_info
        if network_info is None:
            return

        if self._has_direct_passthrough_port(network_info):
            # In case of VNIC_TYPES_DIRECT_PASSTHROUGH ports we create
            # pci request per direct passthrough port. Therefore we can trust
            # that pci_slot value in the vif is correct.
            direct_passthrough_pci_addresses = [
                vif['profile']['pci_slot']
                for vif in network_info
                if (vif['vnic_type'] in
                    network_model.VNIC_TYPES_DIRECT_PASSTHROUGH and
                    vif['profile'].get('pci_slot') is not None)
            ]

            # use detach_pci_devices to avoid failure in case of
            # multiple guest direct passthrough ports with the same MAC
            # (protection use-case, ports are on different physical
            # interfaces)
            pci_devs = pci_manager.get_instance_pci_devs(instance, 'all')
            direct_passthrough_pci_addresses = (
                [pci_dev for pci_dev in pci_devs
                 if pci_dev.address in direct_passthrough_pci_addresses])
            self._detach_pci_devices(guest, direct_passthrough_pci_addresses)

    def _set_host_enabled(self, enabled,
                          disable_reason=DISABLE_REASON_UNDEFINED):
        """Enables / Disables the compute service on this host.

           This doesn't override non-automatic disablement with an automatic
           setting; thereby permitting operators to keep otherwise
           healthy hosts out of rotation.
        """

        status_name = {True: 'disabled',
                       False: 'enabled'}

        disable_service = not enabled

        ctx = nova_context.get_admin_context()
        try:
            service = objects.Service.get_by_compute_host(ctx, CONF.host)

            if service.disabled != disable_service:
                # Note(jang): this is a quick fix to stop operator-
                # disabled compute hosts from re-enabling themselves
                # automatically. We prefix any automatic reason code
                # with a fixed string. We only re-enable a host
                # automatically if we find that string in place.
                # This should probably be replaced with a separate flag.
                if not service.disabled or (
                        service.disabled_reason and
                        service.disabled_reason.startswith(DISABLE_PREFIX)):
                    service.disabled = disable_service
                    service.disabled_reason = (
                       DISABLE_PREFIX + disable_reason
                       if disable_service and disable_reason else
                           DISABLE_REASON_UNDEFINED)
                    service.save()
                    LOG.debug('Updating compute service status to %s',
                              status_name[disable_service])
                else:
                    LOG.debug('Not overriding manual compute service '
                              'status with: %s',
                              status_name[disable_service])
        except exception.ComputeHostNotFound:
            LOG.warning('Cannot update service status on host "%s" '
                        'since it is not registered.', CONF.host)
        except Exception:
            LOG.warning('Cannot update service status on host "%s" '
                        'due to an unexpected exception.', CONF.host,
                        exc_info=True)

        if enabled:
            mount.get_manager().host_up(self._host)
        else:
            mount.get_manager().host_down()

    def _get_guest_cpu_model_config(self):
        mode = CONF.libvirt.cpu_mode
        model = CONF.libvirt.cpu_model
        extra_flags = set([flag.lower() for flag in
            CONF.libvirt.cpu_model_extra_flags])

        if (CONF.libvirt.virt_type == "kvm" or
            CONF.libvirt.virt_type == "qemu"):
            if mode is None:
                caps = self._host.get_capabilities()
                # AArch64 lacks 'host-model' support because neither libvirt
                # nor QEMU are able to tell what the host CPU model exactly is.
                # And there is no CPU description code for ARM(64) at this
                # point.

                # Also worth noting: 'host-passthrough' mode will completely
                # break live migration, *unless* all the Compute nodes (running
                # libvirtd) have *identical* CPUs.
                if caps.host.cpu.arch == fields.Architecture.AARCH64:
                    mode = "host-passthrough"
                    LOG.info('CPU mode "host-passthrough" was chosen. Live '
                             'migration can break unless all compute nodes '
                             'have identical cpus. AArch64 does not support '
                             'other modes.')
                else:
                    mode = "host-model"
            if mode == "none":
                return vconfig.LibvirtConfigGuestCPU()
        else:
            if mode is None or mode == "none":
                return None

        if ((CONF.libvirt.virt_type != "kvm" and
             CONF.libvirt.virt_type != "qemu")):
            msg = _("Config requested an explicit CPU model, but "
                    "the current libvirt hypervisor '%s' does not "
                    "support selecting CPU models") % CONF.libvirt.virt_type
            raise exception.Invalid(msg)

        if mode == "custom" and model is None:
            msg = _("Config requested a custom CPU model, but no "
                    "model name was provided")
            raise exception.Invalid(msg)
        elif mode != "custom" and model is not None:
            msg = _("A CPU model name should not be set when a "
                    "host CPU model is requested")
            raise exception.Invalid(msg)
        # FIXME (kchamart): We're intentionally restricting the choices
        # (in the conf/libvirt.py) for 'extra_flags` to just 'PCID', to
        # address the immediate guest performance degradation caused by
        # "Meltdown" CVE fixes on certain Intel CPU models.  In a future
        # patch, we will:
        # (a) Remove the restriction of choices for 'extra_flags',
        #     allowing to add / remove additional CPU flags, as it will
        #     make way for other useful features.
        # (b) Remove the below check for "host-model", as it is a
        #     valid configuration to supply additional CPU flags to it.
        # (c) Revisit and fix the warnings / exception handling for
        #     different combinations of CPU modes and 'extra_flags'.
        elif ((mode == "host-model" or mode == "host-passthrough") and
              extra_flags):
            extra_flags = []
            LOG.warning("Setting extra CPU flags is only valid in "
                        "combination with a custom CPU model. Refer "
                        "to the 'nova.conf' documentation for "
                        "'[libvirt]/cpu_model_extra_flags'")

        LOG.debug("CPU mode '%(mode)s' model '%(model)s' was chosen, "
                  "with extra flags: '%(extra_flags)s'",
                  {'mode': mode,
                   'model': (model or ""),
                   'extra_flags': (extra_flags or "")})

        cpu = vconfig.LibvirtConfigGuestCPU()
        cpu.mode = mode
        cpu.model = model

        # NOTE (kchamart): Currently there's no existing way to ask if a
        # given CPU model + CPU flags combination is supported by KVM &
        # a specific QEMU binary.  However, libvirt runs the 'CPUID'
        # command upfront -- before even a Nova instance (a QEMU
        # process) is launched -- to construct CPU models and check
        # their validity; so we are good there.  In the long-term,
        # upstream libvirt intends to add an additional new API that can
        # do fine-grained validation of a certain CPU model + CPU flags
        # against a specific QEMU binary (the libvirt RFE bug for that:
        # https://bugzilla.redhat.com/show_bug.cgi?id=1559832).
        for flag in extra_flags:
            cpu.add_feature(vconfig.LibvirtConfigGuestCPUFeature(flag))

        return cpu

    def _get_guest_cpu_config(self, flavor, image_meta,
                              guest_cpu_numa_config, instance_numa_topology):
        cpu = self._get_guest_cpu_model_config()

        if cpu is None:
            return None

        topology = hardware.get_best_cpu_topology(
                flavor, image_meta, numa_topology=instance_numa_topology)

        cpu.sockets = topology.sockets
        cpu.cores = topology.cores
        cpu.threads = topology.threads
        cpu.numa = guest_cpu_numa_config

        return cpu

    def _get_guest_disk_config(self, instance, name, disk_mapping, inst_type,
                               image_type=None):
        disk_unit = None
        disk = self.image_backend.by_name(instance, name, image_type)
        if (name == 'disk.config' and image_type == 'rbd' and
                not disk.exists()):
            # This is likely an older config drive that has not been migrated
            # to rbd yet. Try to fall back on 'flat' image type.
            # TODO(melwitt): Add online migration of some sort so we can
            # remove this fall back once we know all config drives are in rbd.
            # NOTE(vladikr): make sure that the flat image exist, otherwise
            # the image will be created after the domain definition.
            flat_disk = self.image_backend.by_name(instance, name, 'flat')
            if flat_disk.exists():
                disk = flat_disk
                LOG.debug('Config drive not found in RBD, falling back to the '
                          'instance directory', instance=instance)
        disk_info = disk_mapping[name]
        if 'unit' in disk_mapping and disk_info['bus'] == 'scsi':
            disk_unit = disk_mapping['unit']
            disk_mapping['unit'] += 1  # Increments for the next disk added
        conf = disk.libvirt_info(disk_info['bus'],
                                 disk_info['dev'],
                                 disk_info['type'],
                                 self.disk_cachemode,
                                 inst_type['extra_specs'],
                                 self._host.get_version(),
                                 disk_unit=disk_unit)
        return conf

    def _get_guest_fs_config(self, instance, name, image_type=None):
        disk = self.image_backend.by_name(instance, name, image_type)
        return disk.libvirt_fs_info("/", "ploop")

    def _get_guest_storage_config(self, instance, image_meta,
                                  disk_info,
                                  rescue, block_device_info,
                                  inst_type, os_type):
        devices = []
        disk_mapping = disk_info['mapping']

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        mount_rootfs = CONF.libvirt.virt_type == "lxc"
        scsi_controller = self._get_scsi_controller(image_meta)

        if scsi_controller and scsi_controller.model == 'virtio-scsi':
            # The virtio-scsi can handle up to 256 devices but the
            # optional element "address" must be defined to describe
            # where the device is placed on the controller (see:
            # LibvirtConfigGuestDeviceAddressDrive).
            #
            # Note about why it's added in disk_mapping: It's not
            # possible to pass an 'int' by reference in Python, so we
            # use disk_mapping as container to keep reference of the
            # unit added and be able to increment it for each disk
            # added.
            #
            # NOTE(jaypipes,melwitt): If this is a boot-from-volume instance,
            # we need to start the disk mapping unit at 1 since we set the
            # bootable volume's unit to 0 for the bootable volume.
            disk_mapping['unit'] = 0
            if self._is_booted_from_volume(block_device_info):
                disk_mapping['unit'] = 1

        def _get_ephemeral_devices():
            eph_devices = []
            for idx, eph in enumerate(
                driver.block_device_info_get_ephemerals(
                    block_device_info)):
                diskeph = self._get_guest_disk_config(
                    instance,
                    blockinfo.get_eph_disk(idx),
                    disk_mapping, inst_type)
                eph_devices.append(diskeph)
            return eph_devices

        if mount_rootfs:
            fs = vconfig.LibvirtConfigGuestFilesys()
            fs.source_type = "mount"
            fs.source_dir = os.path.join(
                libvirt_utils.get_instance_path(instance), 'rootfs')
            devices.append(fs)
        elif (os_type == fields.VMMode.EXE and
              CONF.libvirt.virt_type == "parallels"):
            if rescue:
                fsrescue = self._get_guest_fs_config(instance, "disk.rescue")
                devices.append(fsrescue)

                fsos = self._get_guest_fs_config(instance, "disk")
                fsos.target_dir = "/mnt/rescue"
                devices.append(fsos)
            else:
                if 'disk' in disk_mapping:
                    fs = self._get_guest_fs_config(instance, "disk")
                    devices.append(fs)
                devices = devices + _get_ephemeral_devices()
        else:

            if rescue:
                diskrescue = self._get_guest_disk_config(instance,
                                                         'disk.rescue',
                                                         disk_mapping,
                                                         inst_type)
                devices.append(diskrescue)

                diskos = self._get_guest_disk_config(instance,
                                                     'disk',
                                                     disk_mapping,
                                                     inst_type)
                devices.append(diskos)
            else:
                if 'disk' in disk_mapping:
                    diskos = self._get_guest_disk_config(instance,
                                                         'disk',
                                                         disk_mapping,
                                                         inst_type)
                    devices.append(diskos)

                if 'disk.local' in disk_mapping:
                    disklocal = self._get_guest_disk_config(instance,
                                                            'disk.local',
                                                            disk_mapping,
                                                            inst_type)
                    devices.append(disklocal)
                    instance.default_ephemeral_device = (
                        block_device.prepend_dev(disklocal.target_dev))

                devices = devices + _get_ephemeral_devices()

                if 'disk.swap' in disk_mapping:
                    diskswap = self._get_guest_disk_config(instance,
                                                           'disk.swap',
                                                           disk_mapping,
                                                           inst_type)
                    devices.append(diskswap)
                    instance.default_swap_device = (
                        block_device.prepend_dev(diskswap.target_dev))

            config_name = 'disk.config.rescue' if rescue else 'disk.config'
            if config_name in disk_mapping:
                diskconfig = self._get_guest_disk_config(
                    instance, config_name, disk_mapping, inst_type,
                    self._get_disk_config_image_type())
                devices.append(diskconfig)

        for vol in block_device.get_bdms_to_connect(block_device_mapping,
                                                   mount_rootfs):
            connection_info = vol['connection_info']
            vol_dev = block_device.prepend_dev(vol['mount_device'])
            info = disk_mapping[vol_dev]
            self._connect_volume(connection_info, info, instance)
            if scsi_controller and scsi_controller.model == 'virtio-scsi':
                # Check if this is the bootable volume when in a
                # boot-from-volume instance, and if so, ensure the unit
                # attribute is 0.
                if vol.get('boot_index') == 0:
                    info['unit'] = 0
                else:
                    info['unit'] = disk_mapping['unit']
                    disk_mapping['unit'] += 1
            cfg = self._get_volume_config(connection_info, info)
            devices.append(cfg)
            vol['connection_info'] = connection_info
            vol.save()

        for d in devices:
            self._set_cache_mode(d)

        if scsi_controller:
            devices.append(scsi_controller)

        return devices

    @staticmethod
    def _get_scsi_controller(image_meta):
        """Return scsi controller or None based on image meta"""
        # TODO(sahid): should raise an exception for an invalid controller
        if image_meta.properties.get('hw_scsi_model'):
            hw_scsi_model = image_meta.properties.hw_scsi_model
            scsi_controller = vconfig.LibvirtConfigGuestController()
            scsi_controller.type = 'scsi'
            scsi_controller.model = hw_scsi_model
            scsi_controller.index = 0
            return scsi_controller

    def _get_host_sysinfo_serial_hardware(self):
        """Get a UUID from the host hardware

        Get a UUID for the host hardware reported by libvirt.
        This is typically from the SMBIOS data, unless it has
        been overridden in /etc/libvirt/libvirtd.conf
        """
        caps = self._host.get_capabilities()
        return caps.host.uuid

    def _get_host_sysinfo_serial_os(self):
        """Get a UUID from the host operating system

        Get a UUID for the host operating system. Modern Linux
        distros based on systemd provide a /etc/machine-id
        file containing a UUID. This is also provided inside
        systemd based containers and can be provided by other
        init systems too, since it is just a plain text file.
        """
        if not os.path.exists("/etc/machine-id"):
            msg = _("Unable to get host UUID: /etc/machine-id does not exist")
            raise exception.InternalError(msg)

        with open("/etc/machine-id") as f:
            # We want to have '-' in the right place
            # so we parse & reformat the value
            lines = f.read().split()
            if not lines:
                msg = _("Unable to get host UUID: /etc/machine-id is empty")
                raise exception.InternalError(msg)

            return str(uuid.UUID(lines[0]))

    def _get_host_sysinfo_serial_auto(self):
        if os.path.exists("/etc/machine-id"):
            return self._get_host_sysinfo_serial_os()
        else:
            return self._get_host_sysinfo_serial_hardware()

    def _get_guest_config_sysinfo(self, instance):
        sysinfo = vconfig.LibvirtConfigGuestSysinfo()

        sysinfo.system_manufacturer = version.vendor_string()
        sysinfo.system_product = version.product_string()
        sysinfo.system_version = version.version_string_with_package()

        sysinfo.system_serial = self._sysinfo_serial_func()
        sysinfo.system_uuid = instance.uuid

        sysinfo.system_family = "Virtual Machine"

        return sysinfo

    def _get_guest_pci_device(self, pci_device):

        dbsf = pci_utils.parse_address(pci_device.address)
        dev = vconfig.LibvirtConfigGuestHostdevPCI()
        dev.domain, dev.bus, dev.slot, dev.function = dbsf

        # only kvm support managed mode
        if CONF.libvirt.virt_type in ('xen', 'parallels',):
            dev.managed = 'no'
        if CONF.libvirt.virt_type in ('kvm', 'qemu'):
            dev.managed = 'yes'

        return dev

    def _get_guest_config_meta(self, instance):
        """Get metadata config for guest."""

        meta = vconfig.LibvirtConfigGuestMetaNovaInstance()
        meta.package = version.version_string_with_package()
        meta.name = instance.display_name
        meta.creationTime = time.time()

        if instance.image_ref not in ("", None):
            meta.roottype = "image"
            meta.rootid = instance.image_ref

        system_meta = instance.system_metadata
        ometa = vconfig.LibvirtConfigGuestMetaNovaOwner()
        ometa.userid = instance.user_id
        ometa.username = system_meta.get('owner_user_name', 'N/A')
        ometa.projectid = instance.project_id
        ometa.projectname = system_meta.get('owner_project_name', 'N/A')
        meta.owner = ometa

        fmeta = vconfig.LibvirtConfigGuestMetaNovaFlavor()
        flavor = instance.flavor
        fmeta.name = flavor.name
        fmeta.memory = flavor.memory_mb
        fmeta.vcpus = flavor.vcpus
        fmeta.ephemeral = flavor.ephemeral_gb
        fmeta.disk = flavor.root_gb
        fmeta.swap = flavor.swap

        meta.flavor = fmeta

        return meta

    def _machine_type_mappings(self):
        mappings = {}
        for mapping in CONF.libvirt.hw_machine_type:
            host_arch, _, machine_type = mapping.partition('=')
            mappings[host_arch] = machine_type
        return mappings

    def _get_machine_type(self, image_meta, caps):
        # The underlying machine type can be set as an image attribute,
        # or otherwise based on some architecture specific defaults

        mach_type = None

        if image_meta.properties.get('hw_machine_type') is not None:
            mach_type = image_meta.properties.hw_machine_type
        else:
            # For ARM systems we will default to vexpress-a15 for armv7
            # and virt for aarch64
            if caps.host.cpu.arch == fields.Architecture.ARMV7:
                mach_type = "vexpress-a15"

            if caps.host.cpu.arch == fields.Architecture.AARCH64:
                mach_type = "virt"

            if caps.host.cpu.arch in (fields.Architecture.S390,
                                      fields.Architecture.S390X):
                mach_type = 's390-ccw-virtio'

            # If set in the config, use that as the default.
            if CONF.libvirt.hw_machine_type:
                mappings = self._machine_type_mappings()
                mach_type = mappings.get(caps.host.cpu.arch)

        return mach_type

    @staticmethod
    def _create_idmaps(klass, map_strings):
        idmaps = []
        if len(map_strings) > 5:
            map_strings = map_strings[0:5]
            LOG.warning("Too many id maps, only included first five.")
        for map_string in map_strings:
            try:
                idmap = klass()
                values = [int(i) for i in map_string.split(":")]
                idmap.start = values[0]
                idmap.target = values[1]
                idmap.count = values[2]
                idmaps.append(idmap)
            except (ValueError, IndexError):
                LOG.warning("Invalid value for id mapping %s", map_string)
        return idmaps

    def _get_guest_idmaps(self):
        id_maps = []
        if CONF.libvirt.virt_type == 'lxc' and CONF.libvirt.uid_maps:
            uid_maps = self._create_idmaps(vconfig.LibvirtConfigGuestUIDMap,
                                           CONF.libvirt.uid_maps)
            id_maps.extend(uid_maps)
        if CONF.libvirt.virt_type == 'lxc' and CONF.libvirt.gid_maps:
            gid_maps = self._create_idmaps(vconfig.LibvirtConfigGuestGIDMap,
                                           CONF.libvirt.gid_maps)
            id_maps.extend(gid_maps)
        return id_maps

    def _update_guest_cputune(self, guest, flavor, virt_type):
        is_able = self._host.is_cpu_control_policy_capable()

        cputuning = ['shares', 'period', 'quota']
        wants_cputune = any([k for k in cputuning
            if "quota:cpu_" + k in flavor.extra_specs.keys()])

        if wants_cputune and not is_able:
            raise exception.UnsupportedHostCPUControlPolicy()

        if not is_able or virt_type not in ('lxc', 'kvm', 'qemu'):
            return

        if guest.cputune is None:
            guest.cputune = vconfig.LibvirtConfigGuestCPUTune()
            # Setting the default cpu.shares value to be a value
            # dependent on the number of vcpus
        guest.cputune.shares = 1024 * guest.vcpus

        for name in cputuning:
            key = "quota:cpu_" + name
            if key in flavor.extra_specs:
                setattr(guest.cputune, name,
                        int(flavor.extra_specs[key]))

    def _get_cpu_numa_config_from_instance(self, instance_numa_topology,
                                           wants_hugepages):
        if instance_numa_topology:
            guest_cpu_numa = vconfig.LibvirtConfigGuestCPUNUMA()
            for instance_cell in instance_numa_topology.cells:
                guest_cell = vconfig.LibvirtConfigGuestCPUNUMACell()
                guest_cell.id = instance_cell.id
                guest_cell.cpus = instance_cell.cpuset
                guest_cell.memory = instance_cell.memory * units.Ki

                # The vhost-user network backend requires file backed
                # guest memory (ie huge pages) to be marked as shared
                # access, not private, so an external process can read
                # and write the pages.
                #
                # You can't change the shared vs private flag for an
                # already running guest, and since we can't predict what
                # types of NIC may be hotplugged, we have no choice but
                # to unconditionally turn on the shared flag. This has
                # no real negative functional effect on the guest, so
                # is a reasonable approach to take
                if wants_hugepages:
                    guest_cell.memAccess = "shared"
                guest_cpu_numa.cells.append(guest_cell)
            return guest_cpu_numa

    def _has_cpu_policy_support(self):
        for ver in BAD_LIBVIRT_CPU_POLICY_VERSIONS:
            if self._host.has_version(ver):
                ver_ = self._version_to_string(ver)
                raise exception.CPUPinningNotSupported(reason=_(
                    'Invalid libvirt version %(version)s') % {'version': ver_})
        return True

    def _wants_hugepages(self, host_topology, instance_topology):
        """Determine if the guest / host topology implies the
           use of huge pages for guest RAM backing
        """

        if host_topology is None or instance_topology is None:
            return False

        avail_pagesize = [page.size_kb
                          for page in host_topology.cells[0].mempages]
        avail_pagesize.sort()
        # Remove smallest page size as that's not classed as a largepage
        avail_pagesize = avail_pagesize[1:]

        # See if we have page size set
        for cell in instance_topology.cells:
            if (cell.pagesize is not None and
                cell.pagesize in avail_pagesize):
                return True

        return False

    def _get_guest_numa_config(self, instance_numa_topology, flavor,
                               allowed_cpus=None, image_meta=None):
        """Returns the config objects for the guest NUMA specs.

        Determines the CPUs that the guest can be pinned to if the guest
        specifies a cell topology and the host supports it. Constructs the
        libvirt XML config object representing the NUMA topology selected
        for the guest. Returns a tuple of:

            (cpu_set, guest_cpu_tune, guest_cpu_numa, guest_numa_tune)

        With the following caveats:

            a) If there is no specified guest NUMA topology, then
               all tuple elements except cpu_set shall be None. cpu_set
               will be populated with the chosen CPUs that the guest
               allowed CPUs fit within, which could be the supplied
               allowed_cpus value if the host doesn't support NUMA
               topologies.

            b) If there is a specified guest NUMA topology, then
               cpu_set will be None and guest_cpu_numa will be the
               LibvirtConfigGuestCPUNUMA object representing the guest's
               NUMA topology. If the host supports NUMA, then guest_cpu_tune
               will contain a LibvirtConfigGuestCPUTune object representing
               the optimized chosen cells that match the host capabilities
               with the instance's requested topology. If the host does
               not support NUMA, then guest_cpu_tune and guest_numa_tune
               will be None.
        """

        if (not self._has_numa_support() and
                instance_numa_topology is not None):
            # We should not get here, since we should have avoided
            # reporting NUMA topology from _get_host_numa_topology
            # in the first place. Just in case of a scheduler
            # mess up though, raise an exception
            raise exception.NUMATopologyUnsupported()

        topology = self._get_host_numa_topology()

        # We have instance NUMA so translate it to the config class
        guest_cpu_numa_config = self._get_cpu_numa_config_from_instance(
                instance_numa_topology,
                self._wants_hugepages(topology, instance_numa_topology))

        if not guest_cpu_numa_config:
            # No NUMA topology defined for instance - let the host kernel deal
            # with the NUMA effects.
            # TODO(ndipanov): Attempt to spread the instance
            # across NUMA nodes and expose the topology to the
            # instance as an optimisation
            return GuestNumaConfig(allowed_cpus, None, None, None)
        else:
            if topology:
                # Now get the CpuTune configuration from the numa_topology
                guest_cpu_tune = vconfig.LibvirtConfigGuestCPUTune()
                guest_numa_tune = vconfig.LibvirtConfigGuestNUMATune()
                emupcpus = []

                numa_mem = vconfig.LibvirtConfigGuestNUMATuneMemory()
                numa_memnodes = [vconfig.LibvirtConfigGuestNUMATuneMemNode()
                                 for _ in guest_cpu_numa_config.cells]

                emulator_threads_isolated = (
                    instance_numa_topology.emulator_threads_isolated)

                vcpus_rt = set([])
                wants_realtime = hardware.is_realtime_enabled(flavor)
                if wants_realtime:
                    if not self._host.has_min_version(
                            MIN_LIBVIRT_REALTIME_VERSION):
                        raise exception.RealtimePolicyNotSupported()
                    # Prepare realtime config for libvirt
                    vcpus_rt = hardware.vcpus_realtime_topology(
                        flavor, image_meta)
                    vcpusched = vconfig.LibvirtConfigGuestCPUTuneVCPUSched()
                    vcpusched.vcpus = vcpus_rt
                    vcpusched.scheduler = "fifo"
                    vcpusched.priority = (
                        CONF.libvirt.realtime_scheduler_priority)
                    guest_cpu_tune.vcpusched.append(vcpusched)

                # TODO(sahid): Defining domain topology should be
                # refactored.
                for host_cell in topology.cells:
                    for guest_node_id, guest_config_cell in enumerate(
                            guest_cpu_numa_config.cells):
                        if guest_config_cell.id == host_cell.id:
                            node = numa_memnodes[guest_node_id]
                            node.cellid = guest_node_id
                            node.nodeset = [host_cell.id]
                            node.mode = "strict"

                            numa_mem.nodeset.append(host_cell.id)

                            object_numa_cell = (
                                    instance_numa_topology.cells[guest_node_id]
                                )
                            for cpu in guest_config_cell.cpus:
                                pin_cpuset = (
                                    vconfig.LibvirtConfigGuestCPUTuneVCPUPin())
                                pin_cpuset.id = cpu
                                # If there is pinning information in the cell
                                # we pin to individual CPUs, otherwise we float
                                # over the whole host NUMA node

                                if (object_numa_cell.cpu_pinning and
                                        self._has_cpu_policy_support()):
                                    pcpu = object_numa_cell.cpu_pinning[cpu]
                                    pin_cpuset.cpuset = set([pcpu])
                                else:
                                    pin_cpuset.cpuset = host_cell.cpuset
                                if emulator_threads_isolated:
                                    if object_numa_cell.cpuset_reserved:
                                        emupcpus.extend(
                                            object_numa_cell.cpuset_reserved)
                                elif not wants_realtime or cpu not in vcpus_rt:
                                    # - If realtime IS NOT enabled, the
                                    #   emulator threads are allowed to float
                                    #   across all the pCPUs associated with
                                    #   the guest vCPUs ("not wants_realtime"
                                    #   is true, so we add all pcpus)
                                    # - If realtime IS enabled, then at least
                                    #   1 vCPU is required to be set aside for
                                    #   non-realtime usage. The emulator
                                    #   threads are allowed to float acros the
                                    #   pCPUs that are associated with the
                                    #   non-realtime VCPUs (the "cpu not in
                                    #   vcpu_rt" check deals with this
                                    #   filtering)
                                    emupcpus.extend(pin_cpuset.cpuset)
                                guest_cpu_tune.vcpupin.append(pin_cpuset)

                # TODO(berrange) When the guest has >1 NUMA node, it will
                # span multiple host NUMA nodes. By pinning emulator threads
                # to the union of all nodes, we guarantee there will be
                # cross-node memory access by the emulator threads when
                # responding to guest I/O operations. The only way to avoid
                # this would be to pin emulator threads to a single node and
                # tell the guest OS to only do I/O from one of its virtual
                # NUMA nodes. This is not even remotely practical.
                #
                # The long term solution is to make use of a new QEMU feature
                # called "I/O Threads" which will let us configure an explicit
                # I/O thread for each guest vCPU or guest NUMA node. It is
                # still TBD how to make use of this feature though, especially
                # how to associate IO threads with guest devices to eliminate
                # cross NUMA node traffic. This is an area of investigation
                # for QEMU community devs.
                emulatorpin = vconfig.LibvirtConfigGuestCPUTuneEmulatorPin()
                emulatorpin.cpuset = set(emupcpus)
                guest_cpu_tune.emulatorpin = emulatorpin
                # Sort the vcpupin list per vCPU id for human-friendlier XML
                guest_cpu_tune.vcpupin.sort(key=operator.attrgetter("id"))

                guest_numa_tune.memory = numa_mem
                guest_numa_tune.memnodes = numa_memnodes

                # normalize cell.id
                for i, (cell, memnode) in enumerate(
                                            zip(guest_cpu_numa_config.cells,
                                                guest_numa_tune.memnodes)):
                    cell.id = i
                    memnode.cellid = i

                return GuestNumaConfig(None, guest_cpu_tune,
                                       guest_cpu_numa_config,
                                       guest_numa_tune)
            else:
                return GuestNumaConfig(allowed_cpus, None,
                                       guest_cpu_numa_config, None)

    def _get_guest_os_type(self, virt_type):
        """Returns the guest OS type based on virt type."""
        if virt_type == "lxc":
            ret = fields.VMMode.EXE
        elif virt_type == "uml":
            ret = fields.VMMode.UML
        elif virt_type == "xen":
            ret = fields.VMMode.XEN
        else:
            ret = fields.VMMode.HVM
        return ret

    def _set_guest_for_rescue(self, rescue, guest, inst_path, virt_type,
                              root_device_name):
        if rescue.get('kernel_id'):
            guest.os_kernel = os.path.join(inst_path, "kernel.rescue")
            guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
            if virt_type == "qemu":
                guest.os_cmdline += " no_timer_check"
        if rescue.get('ramdisk_id'):
            guest.os_initrd = os.path.join(inst_path, "ramdisk.rescue")

    def _set_guest_for_inst_kernel(self, instance, guest, inst_path, virt_type,
                                root_device_name, image_meta):
        guest.os_kernel = os.path.join(inst_path, "kernel")
        guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
        if virt_type == "qemu":
            guest.os_cmdline += " no_timer_check"
        if instance.ramdisk_id:
            guest.os_initrd = os.path.join(inst_path, "ramdisk")
        # we only support os_command_line with images with an explicit
        # kernel set and don't want to break nova if there's an
        # os_command_line property without a specified kernel_id param
        if image_meta.properties.get("os_command_line"):
            guest.os_cmdline = image_meta.properties.os_command_line

    def _set_clock(self, guest, os_type, image_meta, virt_type):
        # NOTE(mikal): Microsoft Windows expects the clock to be in
        # "localtime". If the clock is set to UTC, then you can use a
        # registry key to let windows know, but Microsoft says this is
        # buggy in http://support.microsoft.com/kb/2687252
        clk = vconfig.LibvirtConfigGuestClock()
        if os_type == 'windows':
            LOG.info('Configuring timezone for windows instance to localtime')
            clk.offset = 'localtime'
        else:
            clk.offset = 'utc'
        guest.set_clock(clk)

        if virt_type == "kvm":
            self._set_kvm_timers(clk, os_type, image_meta)

    def _set_kvm_timers(self, clk, os_type, image_meta):
        # TODO(berrange) One day this should be per-guest
        # OS type configurable
        tmpit = vconfig.LibvirtConfigGuestTimer()
        tmpit.name = "pit"
        tmpit.tickpolicy = "delay"

        tmrtc = vconfig.LibvirtConfigGuestTimer()
        tmrtc.name = "rtc"
        tmrtc.tickpolicy = "catchup"

        clk.add_timer(tmpit)
        clk.add_timer(tmrtc)

        guestarch = libvirt_utils.get_arch(image_meta)
        if guestarch in (fields.Architecture.I686,
                         fields.Architecture.X86_64):
            # NOTE(rfolco): HPET is a hardware timer for x86 arch.
            # qemu -no-hpet is not supported on non-x86 targets.
            tmhpet = vconfig.LibvirtConfigGuestTimer()
            tmhpet.name = "hpet"
            tmhpet.present = False
            clk.add_timer(tmhpet)

        # Provide Windows guests with the paravirtualized hyperv timer source.
        # This is the windows equiv of kvm-clock, allowing Windows
        # guests to accurately keep time.
        if os_type == 'windows':
            tmhyperv = vconfig.LibvirtConfigGuestTimer()
            tmhyperv.name = "hypervclock"
            tmhyperv.present = True
            clk.add_timer(tmhyperv)

    def _set_features(self, guest, os_type, caps, virt_type, image_meta):
        if virt_type == "xen":
            # PAE only makes sense in X86
            if caps.host.cpu.arch in (fields.Architecture.I686,
                                      fields.Architecture.X86_64):
                guest.features.append(vconfig.LibvirtConfigGuestFeaturePAE())

        if (virt_type not in ("lxc", "uml", "parallels", "xen") or
                (virt_type == "xen" and guest.os_type == fields.VMMode.HVM)):
            guest.features.append(vconfig.LibvirtConfigGuestFeatureACPI())
            guest.features.append(vconfig.LibvirtConfigGuestFeatureAPIC())

        if (virt_type in ("qemu", "kvm") and
                os_type == 'windows'):
            hv = vconfig.LibvirtConfigGuestFeatureHyperV()
            hv.relaxed = True

            hv.spinlocks = True
            # Increase spinlock retries - value recommended by
            # KVM maintainers who certify Windows guests
            # with Microsoft
            hv.spinlock_retries = 8191
            hv.vapic = True
            guest.features.append(hv)

        if (virt_type in ("qemu", "kvm") and
                image_meta.properties.get('img_hide_hypervisor_id')):
            guest.features.append(vconfig.LibvirtConfigGuestFeatureKvmHidden())

    def _check_number_of_serial_console(self, num_ports):
        virt_type = CONF.libvirt.virt_type
        if (virt_type in ("kvm", "qemu") and
            num_ports > ALLOWED_QEMU_SERIAL_PORTS):
            raise exception.SerialPortNumberLimitExceeded(
                allowed=ALLOWED_QEMU_SERIAL_PORTS, virt_type=virt_type)

    def _add_video_driver(self, guest, image_meta, flavor):
        VALID_VIDEO_DEVICES = ("vga", "cirrus", "vmvga", "xen", "qxl")
        video = vconfig.LibvirtConfigGuestVideo()
        # NOTE(ldbragst): The following logic sets the video.type
        # depending on supported defaults given the architecture,
        # virtualization type, and features. The video.type attribute can
        # be overridden by the user with image_meta.properties, which
        # is carried out in the next if statement below this one.
        guestarch = libvirt_utils.get_arch(image_meta)
        if guest.os_type == fields.VMMode.XEN:
            video.type = 'xen'
        elif CONF.libvirt.virt_type == 'parallels':
            video.type = 'vga'
        elif guestarch in (fields.Architecture.PPC,
                           fields.Architecture.PPC64,
                           fields.Architecture.PPC64LE):
            # NOTE(ldbragst): PowerKVM doesn't support 'cirrus' be default
            # so use 'vga' instead when running on Power hardware.
            video.type = 'vga'
        elif CONF.spice.enabled:
            video.type = 'qxl'
        if image_meta.properties.get('hw_video_model'):
            video.type = image_meta.properties.hw_video_model
            if (video.type not in VALID_VIDEO_DEVICES):
                raise exception.InvalidVideoMode(model=video.type)

        # Set video memory, only if the flavor's limit is set
        video_ram = image_meta.properties.get('hw_video_ram', 0)
        max_vram = int(flavor.extra_specs.get('hw_video:ram_max_mb', 0))
        if video_ram > max_vram:
            raise exception.RequestedVRamTooHigh(req_vram=video_ram,
                                                 max_vram=max_vram)
        if max_vram and video_ram:
            video.vram = video_ram * units.Mi / units.Ki
        guest.add_device(video)

    def _add_qga_device(self, guest, instance):
        qga = vconfig.LibvirtConfigGuestChannel()
        qga.type = "unix"
        qga.target_name = "org.qemu.guest_agent.0"
        qga.source_path = ("/var/lib/libvirt/qemu/%s.%s.sock" %
                          ("org.qemu.guest_agent.0", instance.name))
        guest.add_device(qga)

    def _add_rng_device(self, guest, flavor):
        rng_device = vconfig.LibvirtConfigGuestRng()
        rate_bytes = flavor.extra_specs.get('hw_rng:rate_bytes', 0)
        period = flavor.extra_specs.get('hw_rng:rate_period', 0)
        if rate_bytes:
            rng_device.rate_bytes = int(rate_bytes)
            rng_device.rate_period = int(period)
        rng_path = CONF.libvirt.rng_dev_path
        if (rng_path and not os.path.exists(rng_path)):
            raise exception.RngDeviceNotExist(path=rng_path)
        rng_device.backend = rng_path
        guest.add_device(rng_device)

    def _set_qemu_guest_agent(self, guest, flavor, instance, image_meta):
        # Enable qga only if the 'hw_qemu_guest_agent' is equal to yes
        if image_meta.properties.get('hw_qemu_guest_agent', False):
            LOG.debug("Qemu guest agent is enabled through image "
                      "metadata", instance=instance)
            self._add_qga_device(guest, instance)
        rng_is_virtio = image_meta.properties.get('hw_rng_model') == 'virtio'
        rng_allowed_str = flavor.extra_specs.get('hw_rng:allowed', '')
        rng_allowed = strutils.bool_from_string(rng_allowed_str)
        if rng_is_virtio and rng_allowed:
            self._add_rng_device(guest, flavor)

    def _get_guest_memory_backing_config(
            self, inst_topology, numatune, flavor):
        wantsmempages = False
        if inst_topology:
            for cell in inst_topology.cells:
                if cell.pagesize:
                    wantsmempages = True
                    break

        wantsrealtime = hardware.is_realtime_enabled(flavor)

        membacking = None
        if wantsmempages:
            pages = self._get_memory_backing_hugepages_support(
                inst_topology, numatune)
            if pages:
                membacking = vconfig.LibvirtConfigGuestMemoryBacking()
                membacking.hugepages = pages
        if wantsrealtime:
            if not membacking:
                membacking = vconfig.LibvirtConfigGuestMemoryBacking()
            membacking.locked = True
            membacking.sharedpages = False

        return membacking

    def _get_memory_backing_hugepages_support(self, inst_topology, numatune):
        if not self._has_numa_support():
            # We should not get here, since we should have avoided
            # reporting NUMA topology from _get_host_numa_topology
            # in the first place. Just in case of a scheduler
            # mess up though, raise an exception
            raise exception.MemoryPagesUnsupported()

        host_topology = self._get_host_numa_topology()

        if host_topology is None:
            # As above, we should not get here but just in case...
            raise exception.MemoryPagesUnsupported()

        # Currently libvirt does not support the smallest
        # pagesize set as a backend memory.
        # https://bugzilla.redhat.com/show_bug.cgi?id=1173507
        avail_pagesize = [page.size_kb
                          for page in host_topology.cells[0].mempages]
        avail_pagesize.sort()
        smallest = avail_pagesize[0]

        pages = []
        for guest_cellid, inst_cell in enumerate(inst_topology.cells):
            if inst_cell.pagesize and inst_cell.pagesize > smallest:
                for memnode in numatune.memnodes:
                    if guest_cellid == memnode.cellid:
                        page = (
                            vconfig.LibvirtConfigGuestMemoryBackingPage())
                        page.nodeset = [guest_cellid]
                        page.size_kb = inst_cell.pagesize
                        pages.append(page)
                        break  # Quit early...
        return pages

    def _get_flavor(self, ctxt, instance, flavor):
        if flavor is not None:
            return flavor
        return instance.flavor

    def _has_uefi_support(self):
        # This means that the host can support uefi booting for guests
        supported_archs = [fields.Architecture.X86_64,
                           fields.Architecture.AARCH64]
        caps = self._host.get_capabilities()
        return ((caps.host.cpu.arch in supported_archs) and
                os.path.exists(DEFAULT_UEFI_LOADER_PATH[caps.host.cpu.arch]))

    def _get_supported_perf_events(self):

        if (len(CONF.libvirt.enabled_perf_events) == 0 or
             not self._host.has_min_version(MIN_LIBVIRT_PERF_VERSION)):
            return []

        supported_events = []
        host_cpu_info = self._get_cpu_info()
        for event in CONF.libvirt.enabled_perf_events:
            if self._supported_perf_event(event, host_cpu_info['features']):
                supported_events.append(event)
        return supported_events

    def _supported_perf_event(self, event, cpu_features):

        libvirt_perf_event_name = LIBVIRT_PERF_EVENT_PREFIX + event.upper()

        if not hasattr(libvirt, libvirt_perf_event_name):
            LOG.warning("Libvirt doesn't support event type %s.", event)
            return False

        if (event in PERF_EVENTS_CPU_FLAG_MAPPING
            and PERF_EVENTS_CPU_FLAG_MAPPING[event] not in cpu_features):
            LOG.warning("Host does not support event type %s.", event)
            return False

        return True

    def _configure_guest_by_virt_type(self, guest, virt_type, caps, instance,
                                      image_meta, flavor, root_device_name):
        if virt_type == "xen":
            if guest.os_type == fields.VMMode.HVM:
                guest.os_loader = CONF.libvirt.xen_hvmloader_path
            else:
                guest.os_cmdline = CONSOLE
        elif virt_type in ("kvm", "qemu"):
            if caps.host.cpu.arch in (fields.Architecture.I686,
                                      fields.Architecture.X86_64):
                guest.sysinfo = self._get_guest_config_sysinfo(instance)
                guest.os_smbios = vconfig.LibvirtConfigGuestSMBIOS()
            hw_firmware_type = image_meta.properties.get('hw_firmware_type')
            if caps.host.cpu.arch == fields.Architecture.AARCH64:
                if not hw_firmware_type:
                    hw_firmware_type = fields.FirmwareType.UEFI
            if hw_firmware_type == fields.FirmwareType.UEFI:
                if self._has_uefi_support():
                    global uefi_logged
                    if not uefi_logged:
                        LOG.warning("uefi support is without some kind of "
                                    "functional testing and therefore "
                                    "considered experimental.")
                        uefi_logged = True
                    guest.os_loader = DEFAULT_UEFI_LOADER_PATH[
                        caps.host.cpu.arch]
                    guest.os_loader_type = "pflash"
                else:
                    raise exception.UEFINotSupported()
            guest.os_mach_type = self._get_machine_type(image_meta, caps)
            if image_meta.properties.get('hw_boot_menu') is None:
                guest.os_bootmenu = strutils.bool_from_string(
                    flavor.extra_specs.get('hw:boot_menu', 'no'))
            else:
                guest.os_bootmenu = image_meta.properties.hw_boot_menu

        elif virt_type == "lxc":
            guest.os_init_path = "/sbin/init"
            guest.os_cmdline = CONSOLE
        elif virt_type == "uml":
            guest.os_kernel = "/usr/bin/linux"
            guest.os_root = root_device_name
        elif virt_type == "parallels":
            if guest.os_type == fields.VMMode.EXE:
                guest.os_init_path = "/sbin/init"

    def _conf_non_lxc_uml(self, virt_type, guest, root_device_name, rescue,
                    instance, inst_path, image_meta, disk_info):
        if rescue:
            self._set_guest_for_rescue(rescue, guest, inst_path, virt_type,
                                       root_device_name)
        elif instance.kernel_id:
            self._set_guest_for_inst_kernel(instance, guest, inst_path,
                                            virt_type, root_device_name,
                                            image_meta)
        else:
            guest.os_boot_dev = blockinfo.get_boot_order(disk_info)

    def _create_consoles(self, virt_type, guest_cfg, instance, flavor,
                         image_meta):
        # NOTE(markus_z): Beware! Below are so many conditionals that it is
        # easy to lose track. Use this chart to figure out your case:
        #
        # case | is serial | has       | is qemu | resulting
        #      | enabled?  | virtlogd? | or kvm? | devices
        # --------------------------------------------------
        #    1 |        no |        no |     no  | pty*
        #    2 |        no |        no |     yes | file + pty
        #    3 |        no |       yes |      no | see case 1
        #    4 |        no |       yes |     yes | pty with logd
        #    5 |       yes |        no |      no | see case 1
        #    6 |       yes |        no |     yes | tcp + pty
        #    7 |       yes |       yes |      no | see case 1
        #    8 |       yes |       yes |     yes | tcp with logd
        #    * exception: virt_type "parallels" doesn't create a device
        if virt_type == 'parallels':
            pass
        elif virt_type not in ("qemu", "kvm"):
            log_path = self._get_console_log_path(instance)
            self._create_pty_device(guest_cfg,
                                    vconfig.LibvirtConfigGuestConsole,
                                    log_path=log_path)
        elif (virt_type in ("qemu", "kvm") and
                  self._is_s390x_guest(image_meta)):
            self._create_consoles_s390x(guest_cfg, instance,
                                        flavor, image_meta)
        elif virt_type in ("qemu", "kvm"):
            self._create_consoles_qemu_kvm(guest_cfg, instance,
                                        flavor, image_meta)

    def _is_s390x_guest(self, image_meta):
        s390x_archs = (fields.Architecture.S390, fields.Architecture.S390X)
        return libvirt_utils.get_arch(image_meta) in s390x_archs

    def _create_consoles_qemu_kvm(self, guest_cfg, instance, flavor,
                                  image_meta):
        char_dev_cls = vconfig.LibvirtConfigGuestSerial
        log_path = self._get_console_log_path(instance)
        if CONF.serial_console.enabled:
            if not self._serial_ports_already_defined(instance):
                num_ports = hardware.get_number_of_serial_ports(flavor,
                                                                image_meta)
                self._check_number_of_serial_console(num_ports)
                self._create_serial_consoles(guest_cfg, num_ports,
                                             char_dev_cls, log_path)
        else:
            self._create_file_device(guest_cfg, instance, char_dev_cls)
        self._create_pty_device(guest_cfg, char_dev_cls, log_path=log_path)

    def _create_consoles_s390x(self, guest_cfg, instance, flavor, image_meta):
        char_dev_cls = vconfig.LibvirtConfigGuestConsole
        log_path = self._get_console_log_path(instance)
        if CONF.serial_console.enabled:
            if not self._serial_ports_already_defined(instance):
                num_ports = hardware.get_number_of_serial_ports(flavor,
                                                                image_meta)
                self._create_serial_consoles(guest_cfg, num_ports,
                                             char_dev_cls, log_path)
        else:
            self._create_file_device(guest_cfg, instance, char_dev_cls,
                                     "sclplm")
        self._create_pty_device(guest_cfg, char_dev_cls, "sclp", log_path)

    def _create_pty_device(self, guest_cfg, char_dev_cls, target_type=None,
                           log_path=None):
        def _create_base_dev():
            consolepty = char_dev_cls()
            consolepty.target_type = target_type
            consolepty.type = "pty"
            return consolepty

        def _create_logd_dev():
            consolepty = _create_base_dev()
            log = vconfig.LibvirtConfigGuestCharDeviceLog()
            log.file = log_path
            consolepty.log = log
            return consolepty

        if CONF.serial_console.enabled:
            if self._is_virtlogd_available():
                return
            else:
                # NOTE(markus_z): You may wonder why this is necessary and
                # so do I. I'm certain that this is *not* needed in any
                # real use case. It is, however, useful if you want to
                # pypass the Nova API and use "virsh console <guest>" on
                # an hypervisor, as this CLI command doesn't work with TCP
                # devices (like the serial console is).
                #     https://bugzilla.redhat.com/show_bug.cgi?id=781467
                # Pypassing the Nova API however is a thing we don't want.
                # Future changes should remove this and fix the unit tests
                # which ask for the existence.
                guest_cfg.add_device(_create_base_dev())
        else:
            if self._is_virtlogd_available():
                guest_cfg.add_device(_create_logd_dev())
            else:
                guest_cfg.add_device(_create_base_dev())

    def _create_file_device(self, guest_cfg, instance, char_dev_cls,
                            target_type=None):
        if self._is_virtlogd_available():
            return

        consolelog = char_dev_cls()
        consolelog.target_type = target_type
        consolelog.type = "file"
        consolelog.source_path = self._get_console_log_path(instance)
        guest_cfg.add_device(consolelog)

    def _serial_ports_already_defined(self, instance):
        try:
            guest = self._host.get_guest(instance)
            if list(self._get_serial_ports_from_guest(guest)):
                # Serial port are already configured for instance that
                # means we are in a context of migration.
                return True
        except exception.InstanceNotFound:
            LOG.debug(
                "Instance does not exist yet on libvirt, we can "
                "safely pass on looking for already defined serial "
                "ports in its domain XML", instance=instance)
        return False

    def _create_serial_consoles(self, guest_cfg, num_ports, char_dev_cls,
                                log_path):
        for port in six.moves.range(num_ports):
            console = char_dev_cls()
            console.port = port
            console.type = "tcp"
            console.listen_host = CONF.serial_console.proxyclient_address
            listen_port = serial_console.acquire_port(console.listen_host)
            console.listen_port = listen_port
            # NOTE: only the first serial console gets the boot messages,
            # that's why we attach the logd subdevice only to that.
            if port == 0 and self._is_virtlogd_available():
                log = vconfig.LibvirtConfigGuestCharDeviceLog()
                log.file = log_path
                console.log = log
            guest_cfg.add_device(console)

    def _cpu_config_to_vcpu_model(self, cpu_config, vcpu_model):
        """Update VirtCPUModel object according to libvirt CPU config.

        :param:cpu_config: vconfig.LibvirtConfigGuestCPU presenting the
                           instance's virtual cpu configuration.
        :param:vcpu_model: VirtCPUModel object. A new object will be created
                           if None.

        :return: Updated VirtCPUModel object, or None if cpu_config is None

        """

        if not cpu_config:
            return
        if not vcpu_model:
            vcpu_model = objects.VirtCPUModel()

        vcpu_model.arch = cpu_config.arch
        vcpu_model.vendor = cpu_config.vendor
        vcpu_model.model = cpu_config.model
        vcpu_model.mode = cpu_config.mode
        vcpu_model.match = cpu_config.match

        if cpu_config.sockets:
            vcpu_model.topology = objects.VirtCPUTopology(
                sockets=cpu_config.sockets,
                cores=cpu_config.cores,
                threads=cpu_config.threads)
        else:
            vcpu_model.topology = None

        features = [objects.VirtCPUFeature(
            name=f.name,
            policy=f.policy) for f in cpu_config.features]
        vcpu_model.features = features

        return vcpu_model

    def _vcpu_model_to_cpu_config(self, vcpu_model):
        """Create libvirt CPU config according to VirtCPUModel object.

        :param:vcpu_model: VirtCPUModel object.

        :return: vconfig.LibvirtConfigGuestCPU.

        """

        cpu_config = vconfig.LibvirtConfigGuestCPU()
        cpu_config.arch = vcpu_model.arch
        cpu_config.model = vcpu_model.model
        cpu_config.mode = vcpu_model.mode
        cpu_config.match = vcpu_model.match
        cpu_config.vendor = vcpu_model.vendor
        if vcpu_model.topology:
            cpu_config.sockets = vcpu_model.topology.sockets
            cpu_config.cores = vcpu_model.topology.cores
            cpu_config.threads = vcpu_model.topology.threads
        if vcpu_model.features:
            for f in vcpu_model.features:
                xf = vconfig.LibvirtConfigGuestCPUFeature()
                xf.name = f.name
                xf.policy = f.policy
                cpu_config.features.add(xf)
        return cpu_config

    def _get_guest_config(self, instance, network_info, image_meta,
                          disk_info, rescue=None, block_device_info=None,
                          context=None):
        """Get config data for parameters.

        :param rescue: optional dictionary that should contain the key
            'ramdisk_id' if a ramdisk is needed for the rescue image and
            'kernel_id' if a kernel is needed for the rescue image.
        """
        flavor = instance.flavor
        inst_path = libvirt_utils.get_instance_path(instance)
        disk_mapping = disk_info['mapping']

        virt_type = CONF.libvirt.virt_type
        guest = vconfig.LibvirtConfigGuest()
        guest.virt_type = virt_type
        guest.name = instance.name
        guest.uuid = instance.uuid
        # We are using default unit for memory: KiB
        guest.memory = flavor.memory_mb * units.Ki
        guest.vcpus = flavor.vcpus
        allowed_cpus = hardware.get_vcpu_pin_set()

        guest_numa_config = self._get_guest_numa_config(
            instance.numa_topology, flavor, allowed_cpus, image_meta)

        guest.cpuset = guest_numa_config.cpuset
        guest.cputune = guest_numa_config.cputune
        guest.numatune = guest_numa_config.numatune

        guest.membacking = self._get_guest_memory_backing_config(
            instance.numa_topology,
            guest_numa_config.numatune,
            flavor)

        guest.metadata.append(self._get_guest_config_meta(instance))
        guest.idmaps = self._get_guest_idmaps()

        for event in self._supported_perf_events:
            guest.add_perf_event(event)

        self._update_guest_cputune(guest, flavor, virt_type)

        guest.cpu = self._get_guest_cpu_config(
            flavor, image_meta, guest_numa_config.numaconfig,
            instance.numa_topology)

        # Notes(yjiang5): we always sync the instance's vcpu model with
        # the corresponding config file.
        instance.vcpu_model = self._cpu_config_to_vcpu_model(
            guest.cpu, instance.vcpu_model)

        if 'root' in disk_mapping:
            root_device_name = block_device.prepend_dev(
                disk_mapping['root']['dev'])
        else:
            root_device_name = None

        if root_device_name:
            # NOTE(yamahata):
            # for nova.api.ec2.cloud.CloudController.get_metadata()
            instance.root_device_name = root_device_name

        guest.os_type = (fields.VMMode.get_from_instance(instance) or
                self._get_guest_os_type(virt_type))
        caps = self._host.get_capabilities()

        self._configure_guest_by_virt_type(guest, virt_type, caps, instance,
                                           image_meta, flavor,
                                           root_device_name)
        if virt_type not in ('lxc', 'uml'):
            self._conf_non_lxc_uml(virt_type, guest, root_device_name, rescue,
                    instance, inst_path, image_meta, disk_info)

        self._set_features(guest, instance.os_type, caps, virt_type,
                           image_meta)
        self._set_clock(guest, instance.os_type, image_meta, virt_type)

        storage_configs = self._get_guest_storage_config(
                instance, image_meta, disk_info, rescue, block_device_info,
                flavor, guest.os_type)
        for config in storage_configs:
            guest.add_device(config)

        for vif in network_info:
            config = self.vif_driver.get_config(
                instance, vif, image_meta,
                flavor, virt_type, self._host)
            guest.add_device(config)

        self._create_consoles(virt_type, guest, instance, flavor, image_meta)

        pointer = self._get_guest_pointer_model(guest.os_type, image_meta)
        if pointer:
            guest.add_device(pointer)

        self._guest_add_spice_channel(guest)

        if self._guest_add_video_device(guest):
            self._add_video_driver(guest, image_meta, flavor)

        # Qemu guest agent only support 'qemu' and 'kvm' hypervisor
        if virt_type in ('qemu', 'kvm'):
            self._set_qemu_guest_agent(guest, flavor, instance, image_meta)

        self._guest_add_pci_devices(guest, instance)

        self._guest_add_watchdog_action(guest, flavor, image_meta)

        self._guest_add_memory_balloon(guest)

        return guest

    @staticmethod
    def _guest_add_spice_channel(guest):
        if (CONF.spice.enabled and CONF.spice.agent_enabled
                and guest.virt_type not in ('lxc', 'uml', 'xen')):
            channel = vconfig.LibvirtConfigGuestChannel()
            channel.type = 'spicevmc'
            channel.target_name = "com.redhat.spice.0"
            guest.add_device(channel)

    @staticmethod
    def _guest_add_memory_balloon(guest):
        virt_type = guest.virt_type
        # Memory balloon device only support 'qemu/kvm' and 'xen' hypervisor
        if (virt_type in ('xen', 'qemu', 'kvm') and
                    CONF.libvirt.mem_stats_period_seconds > 0):
            balloon = vconfig.LibvirtConfigMemoryBalloon()
            if virt_type in ('qemu', 'kvm'):
                balloon.model = 'virtio'
            else:
                balloon.model = 'xen'
            balloon.period = CONF.libvirt.mem_stats_period_seconds
            guest.add_device(balloon)

    @staticmethod
    def _guest_add_watchdog_action(guest, flavor, image_meta):
        # image meta takes precedence over flavor extra specs; disable the
        # watchdog action by default
        watchdog_action = (flavor.extra_specs.get('hw:watchdog_action')
                           or 'disabled')
        watchdog_action = image_meta.properties.get('hw_watchdog_action',
                                                    watchdog_action)
        # NB(sross): currently only actually supported by KVM/QEmu
        if watchdog_action != 'disabled':
            if watchdog_action in fields.WatchdogAction.ALL:
                bark = vconfig.LibvirtConfigGuestWatchdog()
                bark.action = watchdog_action
                guest.add_device(bark)
            else:
                raise exception.InvalidWatchdogAction(action=watchdog_action)

    def _guest_add_pci_devices(self, guest, instance):
        virt_type = guest.virt_type
        if virt_type in ('xen', 'qemu', 'kvm'):
            # Get all generic PCI devices (non-SR-IOV).
            for pci_dev in pci_manager.get_instance_pci_devs(instance):
                guest.add_device(self._get_guest_pci_device(pci_dev))
        else:
            # PCI devices is only supported for hypervisors
            #  'xen', 'qemu' and 'kvm'.
            if pci_manager.get_instance_pci_devs(instance, 'all'):
                raise exception.PciDeviceUnsupportedHypervisor(type=virt_type)

    @staticmethod
    def _guest_add_video_device(guest):
        # NB some versions of libvirt support both SPICE and VNC
        # at the same time. We're not trying to second guess which
        # those versions are. We'll just let libvirt report the
        # errors appropriately if the user enables both.
        add_video_driver = False
        if CONF.vnc.enabled and guest.virt_type not in ('lxc', 'uml'):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "vnc"
            if CONF.vnc.keymap:
                # TODO(stephenfin): There are some issues here that may
                # necessitate deprecating this option entirely in the future.
                # Refer to bug #1682020 for more information.
                graphics.keymap = CONF.vnc.keymap
            graphics.listen = CONF.vnc.vncserver_listen
            guest.add_device(graphics)
            add_video_driver = True
        if CONF.spice.enabled and guest.virt_type not in ('lxc', 'uml', 'xen'):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "spice"
            if CONF.spice.keymap:
                # TODO(stephenfin): There are some issues here that may
                # necessitate deprecating this option entirely in the future.
                # Refer to bug #1682020 for more information.
                graphics.keymap = CONF.spice.keymap
            graphics.listen = CONF.spice.server_listen
            guest.add_device(graphics)
            add_video_driver = True
        return add_video_driver

    def _get_guest_pointer_model(self, os_type, image_meta):
        pointer_model = image_meta.properties.get(
            'hw_pointer_model', CONF.pointer_model)
        if pointer_model is None and CONF.libvirt.use_usb_tablet:
            # TODO(sahid): We set pointer_model to keep compatibility
            # until the next release O*. It means operators can continue
            # to use the deprecated option "use_usb_tablet" or set a
            # specific device to use
            pointer_model = "usbtablet"
            LOG.warning('The option "use_usb_tablet" has been '
                        'deprecated for Newton in favor of the more '
                        'generic "pointer_model". Please update '
                        'nova.conf to address this change.')

        if pointer_model == "usbtablet":
            # We want a tablet if VNC is enabled, or SPICE is enabled and
            # the SPICE agent is disabled. If the SPICE agent is enabled
            # it provides a paravirt mouse which drastically reduces
            # overhead (by eliminating USB polling).
            if CONF.vnc.enabled or (
                    CONF.spice.enabled and not CONF.spice.agent_enabled):
                return self._get_guest_usb_tablet(os_type)
            else:
                if CONF.pointer_model or CONF.libvirt.use_usb_tablet:
                    # For backward compatibility We don't want to break
                    # process of booting an instance if host is configured
                    # to use USB tablet without VNC or SPICE and SPICE
                    # agent disable.
                    LOG.warning('USB tablet requested for guests by host '
                                'configuration. In order to accept this '
                                'request VNC should be enabled or SPICE '
                                'and SPICE agent disabled on host.')
                else:
                    raise exception.UnsupportedPointerModelRequested(
                        model="usbtablet")

    def _get_guest_usb_tablet(self, os_type):
        tablet = None
        if os_type == fields.VMMode.HVM:
            tablet = vconfig.LibvirtConfigGuestInput()
            tablet.type = "tablet"
            tablet.bus = "usb"
        else:
            if CONF.pointer_model or CONF.libvirt.use_usb_tablet:
                # For backward compatibility We don't want to break
                # process of booting an instance if virtual machine mode
                # is not configured as HVM.
                LOG.warning('USB tablet requested for guests by host '
                            'configuration. In order to accept this '
                            'request the machine mode should be '
                            'configured as HVM.')
            else:
                raise exception.UnsupportedPointerModelRequested(
                    model="usbtablet")
        return tablet

    def _get_guest_xml(self, context, instance, network_info, disk_info,
                       image_meta, rescue=None,
                       block_device_info=None):
        # NOTE(danms): Stringifying a NetworkInfo will take a lock. Do
        # this ahead of time so that we don't acquire it while also
        # holding the logging lock.
        network_info_str = str(network_info)
        msg = ('Start _get_guest_xml '
               'network_info=%(network_info)s '
               'disk_info=%(disk_info)s '
               'image_meta=%(image_meta)s rescue=%(rescue)s '
               'block_device_info=%(block_device_info)s' %
               {'network_info': network_info_str, 'disk_info': disk_info,
                'image_meta': image_meta, 'rescue': rescue,
                'block_device_info': block_device_info})
        # NOTE(mriedem): block_device_info can contain auth_password so we
        # need to sanitize the password in the message.
        LOG.debug(strutils.mask_password(msg), instance=instance)
        conf = self._get_guest_config(instance, network_info, image_meta,
                                      disk_info, rescue, block_device_info,
                                      context)
        xml = conf.to_xml()

        LOG.debug('End _get_guest_xml xml=%(xml)s',
                  {'xml': xml}, instance=instance)
        return xml

    def get_info(self, instance):
        """Retrieve information from libvirt for a specific instance.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        :param instance: nova.objects.instance.Instance object
        :returns: An InstanceInfo object
        """
        guest = self._host.get_guest(instance)
        # Kind of ugly but we need to pass host to get_info as for a
        # workaround, see libvirt/compat.py
        return guest.get_info(self._host)

    def _create_domain_setup_lxc(self, instance, image_meta,
                                 block_device_info):
        inst_path = libvirt_utils.get_instance_path(instance)
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        root_disk = block_device.get_root_bdm(block_device_mapping)
        if root_disk:
            disk_info = blockinfo.get_info_from_bdm(
                instance, CONF.libvirt.virt_type, image_meta, root_disk)
            self._connect_volume(root_disk['connection_info'], disk_info,
                                 instance)
            disk_path = root_disk['connection_info']['data']['device_path']

            # NOTE(apmelton) - Even though the instance is being booted from a
            # cinder volume, it is still presented as a local block device.
            # LocalBlockImage is used here to indicate that the instance's
            # disk is backed by a local block device.
            image_model = imgmodel.LocalBlockImage(disk_path)
        else:
            root_disk = self.image_backend.by_name(instance, 'disk')
            image_model = root_disk.get_model(self._conn)

        container_dir = os.path.join(inst_path, 'rootfs')
        fileutils.ensure_tree(container_dir)
        rootfs_dev = disk_api.setup_container(image_model,
                                              container_dir=container_dir)

        try:
            # Save rootfs device to disconnect it when deleting the instance
            if rootfs_dev:
                instance.system_metadata['rootfs_device_name'] = rootfs_dev
            if CONF.libvirt.uid_maps or CONF.libvirt.gid_maps:
                id_maps = self._get_guest_idmaps()
                libvirt_utils.chown_for_id_maps(container_dir, id_maps)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._create_domain_cleanup_lxc(instance)

    def _create_domain_cleanup_lxc(self, instance):
        inst_path = libvirt_utils.get_instance_path(instance)
        container_dir = os.path.join(inst_path, 'rootfs')

        try:
            state = self.get_info(instance).state
        except exception.InstanceNotFound:
            # The domain may not be present if the instance failed to start
            state = None

        if state == power_state.RUNNING:
            # NOTE(uni): Now the container is running with its own private
            # mount namespace and so there is no need to keep the container
            # rootfs mounted in the host namespace
            LOG.debug('Attempting to unmount container filesystem: %s',
                      container_dir, instance=instance)
            disk_api.clean_lxc_namespace(container_dir=container_dir)
        else:
            disk_api.teardown_container(container_dir=container_dir)

    @contextlib.contextmanager
    def _lxc_disk_handler(self, instance, image_meta, block_device_info):
        """Context manager to handle the pre and post instance boot,
           LXC specific disk operations.

           An image or a volume path will be prepared and setup to be
           used by the container, prior to starting it.
           The disk will be disconnected and unmounted if a container has
           failed to start.
        """

        if CONF.libvirt.virt_type != 'lxc':
            yield
            return

        self._create_domain_setup_lxc(instance, image_meta, block_device_info)

        try:
            yield
        finally:
            self._create_domain_cleanup_lxc(instance)

    # TODO(sahid): Consider renaming this to _create_guest.
    def _create_domain(self, xml=None, domain=None,
                       power_on=True, pause=False, post_xml_callback=None):
        """Create a domain.

        Either domain or xml must be passed in. If both are passed, then
        the domain definition is overwritten from the xml.

        :returns guest.Guest: Guest just created
        """
        if xml:
            guest = libvirt_guest.Guest.create(xml, self._host)
            if post_xml_callback is not None:
                post_xml_callback()
        else:
            guest = libvirt_guest.Guest(domain)

        if power_on or pause:
            guest.launch(pause=pause)

        if not utils.is_neutron():
            guest.enable_hairpin()

        return guest

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error('Neutron Reported failure on event '
                  '%(event)s for instance %(uuid)s',
                  {'event': event_name, 'uuid': instance.uuid},
                  instance=instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _get_neutron_events(self, network_info):
        # NOTE(danms): We need to collect any VIFs that are currently
        # down that we expect a down->up event for. Anything that is
        # already up will not undergo that transition, and for
        # anything that might be stale (cache-wise) assume it's
        # already up so we don't block on it.
        return [('network-vif-plugged', vif['id'])
                for vif in network_info if vif.get('active', True) is False]

    def _cleanup_failed_start(self, context, instance, network_info,
                              block_device_info, guest, destroy_disks):
        try:
            if guest and guest.is_active():
                guest.poweroff()
        finally:
            self.cleanup(context, instance, network_info=network_info,
                         block_device_info=block_device_info,
                         destroy_disks=destroy_disks)

    def _create_domain_and_network(self, context, xml, instance, network_info,
                                   block_device_info=None,
                                   power_on=True, reboot=False,
                                   vifs_already_plugged=False,
                                   post_xml_callback=None,
                                   destroy_disks_on_failure=False):

        """Do required network setup and create domain."""
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        for vol in block_device_mapping:
            connection_info = vol['connection_info']

            if (not reboot and 'data' in connection_info and
                    'volume_id' in connection_info['data']):
                volume_id = connection_info['data']['volume_id']
                encryption = encryptors.get_encryption_metadata(
                    context, self._volume_api, volume_id, connection_info)

                if encryption:
                    encryptor = self._get_volume_encryptor(connection_info,
                                                           encryption)
                    encryptor.attach_volume(context, **encryption)

        timeout = CONF.vif_plugging_timeout
        if (self._conn_supports_start_paused and
            utils.is_neutron() and not
            vifs_already_plugged and power_on and timeout):
            events = self._get_neutron_events(network_info)
        else:
            events = []

        pause = bool(events)
        guest = None
        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self.plug_vifs(instance, network_info)
                self.firewall_driver.setup_basic_filtering(instance,
                                                           network_info)
                self.firewall_driver.prepare_instance_filter(instance,
                                                             network_info)
                with self._lxc_disk_handler(instance, instance.image_meta,
                                            block_device_info):
                    guest = self._create_domain(
                        xml, pause=pause, power_on=power_on,
                        post_xml_callback=post_xml_callback)

                self.firewall_driver.apply_instance_filter(instance,
                                                           network_info)
        except exception.VirtualInterfaceCreateException:
            # Neutron reported failure and we didn't swallow it, so
            # bail here
            with excutils.save_and_reraise_exception():
                self._cleanup_failed_start(context, instance, network_info,
                                           block_device_info, guest,
                                           destroy_disks_on_failure)
        except eventlet.timeout.Timeout:
            # We never heard from Neutron
            LOG.warning('Timeout waiting for vif plugging callback for '
                        'instance with vm_state %(vm_state)s and '
                        'task_state %(task_state)s.',
                        {'vm_state': instance.vm_state,
                         'task_state': instance.task_state},
                        instance=instance)
            if CONF.vif_plugging_is_fatal:
                self._cleanup_failed_start(context, instance, network_info,
                                           block_device_info, guest,
                                           destroy_disks_on_failure)
                raise exception.VirtualInterfaceCreateException()
        except Exception:
            # Any other error, be sure to clean up
            LOG.error('Failed to start libvirt guest', instance=instance)
            with excutils.save_and_reraise_exception():
                self._cleanup_failed_start(context, instance, network_info,
                                           block_device_info, guest,
                                           destroy_disks_on_failure)

        # Resume only if domain has been paused
        if pause:
            guest.resume()
        return guest

    def _get_vcpu_total(self):
        """Get available vcpu number of physical computer.

        :returns: the number of cpu core instances can be used.

        """
        try:
            total_pcpus = self._host.get_cpu_count()
        except libvirt.libvirtError:
            LOG.warning("Cannot get the number of cpu, because this "
                        "function is not implemented for this platform. ")
            return 0

        if not CONF.vcpu_pin_set:
            return total_pcpus

        available_ids = hardware.get_vcpu_pin_set()
        # We get the list of online CPUs on the host and see if the requested
        # set falls under these. If not, we retain the old behavior.
        online_pcpus = None
        try:
            online_pcpus = self._host.get_online_cpus()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            LOG.warning(
                "Couldn't retrieve the online CPUs due to a Libvirt "
                "error: %(error)s with error code: %(error_code)s",
                {'error': ex, 'error_code': error_code})
        if online_pcpus:
            if not (available_ids <= online_pcpus):
                msg = (_("Invalid vcpu_pin_set config, one or more of the "
                         "specified cpuset is not online. Online cpuset(s): "
                         "%(online)s, requested cpuset(s): %(req)s"),
                       {'online': sorted(online_pcpus),
                        'req': sorted(available_ids)})
                raise exception.Invalid(msg)
        elif sorted(available_ids)[-1] >= total_pcpus:
            raise exception.Invalid(_("Invalid vcpu_pin_set config, "
                                      "out of hypervisor cpu range."))
        return len(available_ids)

    @staticmethod
    def _get_local_gb_info():
        """Get local storage info of the compute node in GB.

        :returns: A dict containing:
             :total: How big the overall usable filesystem is (in gigabytes)
             :free: How much space is free (in gigabytes)
             :used: How much space is used (in gigabytes)
        """

        if CONF.libvirt.images_type == 'lvm':
            info = lvm.get_volume_group_info(
                               CONF.libvirt.images_volume_group)
        elif CONF.libvirt.images_type == 'rbd':
            info = LibvirtDriver._get_rbd_driver().get_pool_info()
        else:
            info = libvirt_utils.get_fs_info(CONF.instances_path)

        for (k, v) in info.items():
            info[k] = v / units.Gi

        return info

    def _get_vcpu_used(self):
        """Get vcpu usage number of physical computer.

        :returns: The total number of vcpu(s) that are currently being used.

        """

        total = 0

        # Not all libvirt drivers will support the get_vcpus_info()
        #
        # For example, LXC does not have a concept of vCPUs, while
        # QEMU (TCG) traditionally handles all vCPUs in a single
        # thread. So both will report an exception when the vcpus()
        # API call is made. In such a case we should report the
        # guest as having 1 vCPU, since that lets us still do
        # CPU over commit calculations that apply as the total
        # guest count scales.
        #
        # It is also possible that we might see an exception if
        # the guest is just in middle of shutting down. Technically
        # we should report 0 for vCPU usage in this case, but we
        # we can't reliably distinguish the vcpu not supported
        # case from the just shutting down case. Thus we don't know
        # whether to report 1 or 0 for vCPU count.
        #
        # Under-reporting vCPUs is bad because it could conceivably
        # let the scheduler place too many guests on the host. Over-
        # reporting vCPUs is not a problem as it'll auto-correct on
        # the next refresh of usage data.
        #
        # Thus when getting an exception we always report 1 as the
        # vCPU count, as the least worst value.
        for guest in self._host.list_guests():
            try:
                vcpus = guest.get_vcpus_info()
                total += len(list(vcpus))
            except libvirt.libvirtError:
                total += 1
            # NOTE(gtt116): give other tasks a chance.
            greenthread.sleep(0)
        return total

    def _get_instance_capabilities(self):
        """Get hypervisor instance capabilities

        Returns a list of tuples that describe instances the
        hypervisor is capable of hosting.  Each tuple consists
        of the triplet (arch, hypervisor_type, vm_mode).

        :returns: List of tuples describing instance capabilities
        """
        caps = self._host.get_capabilities()
        instance_caps = list()
        for g in caps.guests:
            for dt in g.domtype:
                instance_cap = (
                    fields.Architecture.canonicalize(g.arch),
                    fields.HVType.canonicalize(dt),
                    fields.VMMode.canonicalize(g.ostype))
                instance_caps.append(instance_cap)

        return instance_caps

    def _get_cpu_info(self):
        """Get cpuinfo information.

        Obtains cpu feature from virConnect.getCapabilities.

        :return: see above description

        """

        caps = self._host.get_capabilities()
        cpu_info = dict()

        cpu_info['arch'] = caps.host.cpu.arch
        cpu_info['model'] = caps.host.cpu.model
        cpu_info['vendor'] = caps.host.cpu.vendor

        topology = dict()
        topology['cells'] = len(getattr(caps.host.topology, 'cells', [1]))
        topology['sockets'] = caps.host.cpu.sockets
        topology['cores'] = caps.host.cpu.cores
        topology['threads'] = caps.host.cpu.threads
        cpu_info['topology'] = topology

        features = set()
        for f in caps.host.cpu.features:
            features.add(f.name)
        cpu_info['features'] = features
        return cpu_info

    def _get_pcinet_info(self, vf_address):
        """Returns a dict of NET device."""
        devname = pci_utils.get_net_name_by_vf_pci_address(vf_address)
        if not devname:
            return

        virtdev = self._host.device_lookup_by_name(devname)
        xmlstr = virtdev.XMLDesc(0)
        cfgdev = vconfig.LibvirtConfigNodeDevice()
        cfgdev.parse_str(xmlstr)
        return {'name': cfgdev.name,
                'capabilities': cfgdev.pci_capability.features}

    def _get_pcidev_info(self, devname):
        """Returns a dict of PCI device."""

        def _get_device_type(cfgdev, pci_address):
            """Get a PCI device's device type.

            An assignable PCI device can be a normal PCI device,
            a SR-IOV Physical Function (PF), or a SR-IOV Virtual
            Function (VF). Only normal PCI devices or SR-IOV VFs
            are assignable, while SR-IOV PFs are always owned by
            hypervisor.
            """
            for fun_cap in cfgdev.pci_capability.fun_capability:
                if fun_cap.type == 'virt_functions':
                    return {
                        'dev_type': fields.PciDeviceType.SRIOV_PF,
                    }
                if (fun_cap.type == 'phys_function' and
                    len(fun_cap.device_addrs) != 0):
                    phys_address = "%04x:%02x:%02x.%01x" % (
                        fun_cap.device_addrs[0][0],
                        fun_cap.device_addrs[0][1],
                        fun_cap.device_addrs[0][2],
                        fun_cap.device_addrs[0][3])
                    return {
                        'dev_type': fields.PciDeviceType.SRIOV_VF,
                        'parent_addr': phys_address,
                    }

            # Note(moshele): libvirt < 1.3 reported virt_functions capability
            # only when VFs are enabled. The check below is a workaround
            # to get the correct report regardless of whether or not any
            # VFs are enabled for the device.
            if not self._host.has_min_version(
                MIN_LIBVIRT_PF_WITH_NO_VFS_CAP_VERSION):
                is_physical_function = pci_utils.is_physical_function(
                    *pci_utils.get_pci_address_fields(pci_address))
                if is_physical_function:
                    return {'dev_type': fields.PciDeviceType.SRIOV_PF}

            return {'dev_type': fields.PciDeviceType.STANDARD}

        def _get_device_capabilities(device, address):
            """Get PCI VF device's additional capabilities.

            If a PCI device is a virtual function, this function reads the PCI
            parent's network capabilities (must be always a NIC device) and
            appends this information to the device's dictionary.
            """
            if device.get('dev_type') == fields.PciDeviceType.SRIOV_VF:
                pcinet_info = self._get_pcinet_info(address)
                if pcinet_info:
                    return {'capabilities':
                                {'network': pcinet_info.get('capabilities')}}
            return {}

        virtdev = self._host.device_lookup_by_name(devname)
        xmlstr = virtdev.XMLDesc(0)
        cfgdev = vconfig.LibvirtConfigNodeDevice()
        cfgdev.parse_str(xmlstr)

        address = "%04x:%02x:%02x.%1x" % (
            cfgdev.pci_capability.domain,
            cfgdev.pci_capability.bus,
            cfgdev.pci_capability.slot,
            cfgdev.pci_capability.function)

        device = {
            "dev_id": cfgdev.name,
            "address": address,
            "product_id": "%04x" % cfgdev.pci_capability.product_id,
            "vendor_id": "%04x" % cfgdev.pci_capability.vendor_id,
            }

        device["numa_node"] = cfgdev.pci_capability.numa_node

        # requirement by DataBase Model
        device['label'] = 'label_%(vendor_id)s_%(product_id)s' % device
        device.update(_get_device_type(cfgdev, address))
        device.update(_get_device_capabilities(device, address))
        return device

    def _get_pci_passthrough_devices(self):
        """Get host PCI devices information.

        Obtains pci devices information from libvirt, and returns
        as a JSON string.

        Each device information is a dictionary, with mandatory keys
        of 'address', 'vendor_id', 'product_id', 'dev_type', 'dev_id',
        'label' and other optional device specific information.

        Refer to the objects/pci_device.py for more idea of these keys.

        :returns: a JSON string containing a list of the assignable PCI
                  devices information
        """
        # Bail early if we know we can't support `listDevices` to avoid
        # repeated warnings within a periodic task
        if not getattr(self, '_list_devices_supported', True):
            return jsonutils.dumps([])

        try:
            dev_names = self._host.list_pci_devices() or []
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                self._list_devices_supported = False
                LOG.warning("URI %(uri)s does not support "
                            "listDevices: %(error)s",
                            {'uri': self._uri(), 'error': ex})
                return jsonutils.dumps([])
            else:
                raise

        pci_info = []
        for name in dev_names:
            pci_info.append(self._get_pcidev_info(name))

        return jsonutils.dumps(pci_info)

    def _has_numa_support(self):
        # This means that the host can support LibvirtConfigGuestNUMATune
        # and the nodeset field in LibvirtConfigGuestMemoryBackingPage
        for ver in BAD_LIBVIRT_NUMA_VERSIONS:
            if self._host.has_version(ver):
                if not getattr(self, '_bad_libvirt_numa_version_warn', False):
                    LOG.warning('You are running with libvirt version %s '
                                'which is known to have broken NUMA support. '
                                'Consider patching or updating libvirt on '
                                'this host if you need NUMA support.',
                                self._version_to_string(ver))
                    self._bad_libvirt_numa_version_warn = True
                return False

        caps = self._host.get_capabilities()

        if (caps.host.cpu.arch in (fields.Architecture.I686,
                                   fields.Architecture.X86_64,
                                   fields.Architecture.AARCH64) and
                self._host.has_min_version(hv_type=host.HV_DRIVER_QEMU)):
            return True
        elif (caps.host.cpu.arch in (fields.Architecture.PPC64,
                                     fields.Architecture.PPC64LE) and
                self._host.has_min_version(MIN_LIBVIRT_NUMA_VERSION_PPC,
                                           hv_type=host.HV_DRIVER_QEMU)):
            return True

        return False

    def _get_host_numa_topology(self):
        if not self._has_numa_support():
            return

        caps = self._host.get_capabilities()
        topology = caps.host.topology

        if topology is None or not topology.cells:
            return

        cells = []
        allowed_cpus = hardware.get_vcpu_pin_set()
        online_cpus = self._host.get_online_cpus()
        if allowed_cpus:
            allowed_cpus &= online_cpus
        else:
            allowed_cpus = online_cpus

        def _get_reserved_memory_for_cell(self, cell_id, page_size):
            cell = self._reserved_hugepages.get(cell_id, {})
            return cell.get(page_size, 0)

        for cell in topology.cells:
            cpuset = set(cpu.id for cpu in cell.cpus)
            siblings = sorted(map(set,
                                  set(tuple(cpu.siblings)
                                        if cpu.siblings else ()
                                      for cpu in cell.cpus)
                                  ))
            cpuset &= allowed_cpus
            siblings = [sib & allowed_cpus for sib in siblings]
            # Filter out singles and empty sibling sets that may be left
            siblings = [sib for sib in siblings if len(sib) > 1]

            mempages = [
                objects.NUMAPagesTopology(
                    size_kb=pages.size,
                    total=pages.total,
                    used=0,
                    reserved=_get_reserved_memory_for_cell(
                        self, cell.id, pages.size))
                for pages in cell.mempages]

            cell = objects.NUMACell(id=cell.id, cpuset=cpuset,
                                    memory=cell.memory / units.Ki,
                                    cpu_usage=0, memory_usage=0,
                                    siblings=siblings,
                                    pinned_cpus=set([]),
                                    mempages=mempages)
            cells.append(cell)

        return objects.NUMATopology(cells=cells)

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.
        """
        vol_usage = []

        for instance_bdms in compute_host_bdms:
            instance = instance_bdms['instance']

            for bdm in instance_bdms['instance_bdms']:
                mountpoint = bdm['device_name']
                if mountpoint.startswith('/dev/'):
                    mountpoint = mountpoint[5:]
                volume_id = bdm['volume_id']

                LOG.debug("Trying to get stats for the volume %s",
                          volume_id, instance=instance)
                vol_stats = self.block_stats(instance, mountpoint)

                if vol_stats:
                    stats = dict(volume=volume_id,
                                 instance=instance,
                                 rd_req=vol_stats[0],
                                 rd_bytes=vol_stats[1],
                                 wr_req=vol_stats[2],
                                 wr_bytes=vol_stats[3])
                    LOG.debug(
                        "Got volume usage stats for the volume=%(volume)s,"
                        " rd_req=%(rd_req)d, rd_bytes=%(rd_bytes)d, "
                        "wr_req=%(wr_req)d, wr_bytes=%(wr_bytes)d",
                        stats, instance=instance)
                    vol_usage.append(stats)

        return vol_usage

    def block_stats(self, instance, disk_id):
        """Note that this function takes an instance name."""
        try:
            guest = self._host.get_guest(instance)

            # TODO(sahid): We are converting all calls from a
            # virDomain object to use nova.virt.libvirt.Guest.
            # We should be able to remove domain at the end.
            domain = guest._domain
            return domain.blockStats(disk_id)
        except libvirt.libvirtError as e:
            errcode = e.get_error_code()
            LOG.info('Getting block stats failed, device might have '
                     'been detached. Instance=%(instance_name)s '
                     'Disk=%(disk)s Code=%(errcode)s Error=%(e)s',
                     {'instance_name': instance.name, 'disk': disk_id,
                      'errcode': errcode, 'e': e},
                     instance=instance)
        except exception.InstanceNotFound:
            LOG.info('Could not find domain in libvirt for instance %s. '
                     'Cannot get block stats for device', instance.name,
                     instance=instance)

    def get_console_pool_info(self, console_type):
        # TODO(mdragon): console proxy should be implemented for libvirt,
        #                in case someone wants to use it with kvm or
        #                such. For now return fake data.
        return {'address': '127.0.0.1',
                'username': 'fakeuser',
                'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_instance_security_rules(self, instance):
        self.firewall_driver.refresh_instance_security_rules(instance)

    def get_inventory(self, nodename):
        """Return a dict, keyed by resource class, of inventory information for
        the supplied node.
        """
        disk_gb = int(self._get_local_gb_info()['total'])
        memory_mb = int(self._host.get_memory_mb_total())
        vcpus = self._get_vcpu_total()
        # NOTE(jaypipes): We leave some fields like allocation_ratio and
        # reserved out of the returned dicts here because, for now at least,
        # the RT injects those values into the inventory dict based on the
        # compute_nodes record values.
        result = {
            fields.ResourceClass.VCPU: {
                'total': vcpus,
                'min_unit': 1,
                'max_unit': vcpus,
                'step_size': 1,
            },
            fields.ResourceClass.MEMORY_MB: {
                'total': memory_mb,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
            },
            fields.ResourceClass.DISK_GB: {
                'total': disk_gb,
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
            },
        }
        return result

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename: unused in this driver
        :returns: dictionary containing resource info
        """

        disk_info_dict = self._get_local_gb_info()
        data = {}

        # NOTE(dprince): calling capabilities before getVersion works around
        # an initialization issue with some versions of Libvirt (1.0.5.5).
        # See: https://bugzilla.redhat.com/show_bug.cgi?id=1000116
        # See: https://bugs.launchpad.net/nova/+bug/1215593
        data["supported_instances"] = self._get_instance_capabilities()

        data["vcpus"] = self._get_vcpu_total()
        data["memory_mb"] = self._host.get_memory_mb_total()
        data["local_gb"] = disk_info_dict['total']
        data["vcpus_used"] = self._get_vcpu_used()
        data["memory_mb_used"] = self._host.get_memory_mb_used()
        data["local_gb_used"] = disk_info_dict['used']
        data["hypervisor_type"] = self._host.get_driver_type()
        data["hypervisor_version"] = self._host.get_version()
        data["hypervisor_hostname"] = self._host.get_hostname()
        # TODO(berrange): why do we bother converting the
        # libvirt capabilities XML into a special JSON format ?
        # The data format is different across all the drivers
        # so we could just return the raw capabilities XML
        # which 'compare_cpu' could use directly
        #
        # That said, arch_filter.py now seems to rely on
        # the libvirt drivers format which suggests this
        # data format needs to be standardized across drivers
        data["cpu_info"] = jsonutils.dumps(self._get_cpu_info())

        disk_free_gb = disk_info_dict['free']
        disk_over_committed = self._get_disk_over_committed_size_total()
        available_least = disk_free_gb * units.Gi - disk_over_committed
        data['disk_available_least'] = available_least / units.Gi

        data['pci_passthrough_devices'] = \
            self._get_pci_passthrough_devices()

        numa_topology = self._get_host_numa_topology()
        if numa_topology:
            data['numa_topology'] = numa_topology._to_json()
        else:
            data['numa_topology'] = None

        return data

    def check_instance_shared_storage_local(self, context, instance):
        """Check if instance files located on shared storage.

        This runs check on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: nova.objects.instance.Instance object
        :returns:
         - tempfile: A dict containing the tempfile info on the destination
                     host
         - None:

            1. If the instance path is not existing.
            2. If the image backend is shared block storage type.
        """
        if self.image_backend.backend().is_shared_block_storage():
            return None

        dirpath = libvirt_utils.get_instance_path(instance)

        if not os.path.exists(dirpath):
            return None

        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug("Creating tmpfile %s to verify with other "
                  "compute node that the instance is on "
                  "the same shared storage.",
                  tmp_file, instance=instance)
        os.close(fd)
        return {"filename": tmp_file}

    def check_instance_shared_storage_remote(self, context, data):
        return os.path.exists(data['filename'])

    def check_instance_shared_storage_cleanup(self, context, data):
        fileutils.delete_if_exists(data["filename"])

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param context: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        :param block_migration: if true, prepare for block migration
        :param disk_over_commit: if true, allow disk over commit
        :returns: a LibvirtLiveMigrateData object
        """
        if disk_over_commit:
            disk_available_gb = dst_compute_info['free_disk_gb']
        else:
            disk_available_gb = dst_compute_info['disk_available_least']
        disk_available_mb = (
            (disk_available_gb * units.Ki) - CONF.reserved_host_disk_mb)

        # Compare CPU
        if not instance.vcpu_model or not instance.vcpu_model.model:
            source_cpu_info = src_compute_info['cpu_info']
            self._compare_cpu(None, source_cpu_info, instance)
        else:
            self._compare_cpu(instance.vcpu_model, None, instance)

        # Create file on storage, to be checked on source host
        filename = self._create_shared_storage_test_file(instance)

        data = objects.LibvirtLiveMigrateData()
        data.filename = filename
        data.image_type = CONF.libvirt.images_type
        data.graphics_listen_addr_vnc = CONF.vnc.vncserver_listen
        data.graphics_listen_addr_spice = CONF.spice.server_listen
        if CONF.serial_console.enabled:
            data.serial_listen_addr = CONF.serial_console.proxyclient_address
        else:
            data.serial_listen_addr = None
        # Notes(eliqiao): block_migration and disk_over_commit are not
        # nullable, so just don't set them if they are None
        if block_migration is not None:
            data.block_migration = block_migration
        if disk_over_commit is not None:
            data.disk_over_commit = disk_over_commit
        data.disk_available_mb = disk_available_mb
        return data

    def cleanup_live_migration_destination_check(self, context,
                                                 dest_check_data):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param context: security context
        """
        filename = dest_check_data.filename
        self._cleanup_shared_storage_test_file(filename)

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data,
                                      block_device_info=None):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
        :param block_device_info: result of _get_instance_block_device_info
        :returns: a LibvirtLiveMigrateData object
        """
        if not isinstance(dest_check_data, migrate_data_obj.LiveMigrateData):
            md_obj = objects.LibvirtLiveMigrateData()
            md_obj.from_legacy_dict(dest_check_data)
            dest_check_data = md_obj

        # Checking shared storage connectivity
        # if block migration, instances_path should not be on shared storage.
        source = CONF.host

        dest_check_data.is_shared_instance_path = (
            self._check_shared_storage_test_file(
                dest_check_data.filename, instance))

        dest_check_data.is_shared_block_storage = (
            self._is_shared_block_storage(instance, dest_check_data,
                                          block_device_info))

        if 'block_migration' not in dest_check_data:
            dest_check_data.block_migration = (
                not dest_check_data.is_on_shared_storage())

        if dest_check_data.block_migration:
            # TODO(eliqiao): Once block_migration flag is removed from the API
            # we can safely remove the if condition
            if dest_check_data.is_on_shared_storage():
                reason = _("Block migration can not be used "
                           "with shared storage.")
                raise exception.InvalidLocalStorage(reason=reason, path=source)
            if 'disk_over_commit' in dest_check_data:
                self._assert_dest_node_has_enough_disk(context, instance,
                                        dest_check_data.disk_available_mb,
                                        dest_check_data.disk_over_commit,
                                        block_device_info)
            if block_device_info:
                bdm = block_device_info.get('block_device_mapping')
                # NOTE(pkoniszewski): libvirt from version 1.2.17 upwards
                # supports selective block device migration. It means that it
                # is possible to define subset of block devices to be copied
                # during migration. If they are not specified - block devices
                # won't be migrated. However, it does not work when live
                # migration is tunnelled through libvirt.
                if bdm and not self._host.has_min_version(
                        MIN_LIBVIRT_BLOCK_LM_WITH_VOLUMES_VERSION):
                    # NOTE(stpierre): if this instance has mapped volumes,
                    # we can't do a block migration, since that will result
                    # in volumes being copied from themselves to themselves,
                    # which is a recipe for disaster.
                    ver = ".".join([str(x) for x in
                                    MIN_LIBVIRT_BLOCK_LM_WITH_VOLUMES_VERSION])
                    msg = (_('Cannot block migrate instance %(uuid)s with'
                             ' mapped volumes. Selective block device'
                             ' migration feature requires libvirt version'
                             ' %(libvirt_ver)s') %
                           {'uuid': instance.uuid, 'libvirt_ver': ver})
                    LOG.error(msg, instance=instance)
                    raise exception.MigrationPreCheckError(reason=msg)
                # NOTE(eliqiao): Selective disk migrations are not supported
                # with tunnelled block migrations so we can block them early.
                if (bdm and
                    (self._block_migration_flags &
                     libvirt.VIR_MIGRATE_TUNNELLED != 0)):
                    msg = (_('Cannot block migrate instance %(uuid)s with'
                             ' mapped volumes. Selective block device'
                             ' migration is not supported with tunnelled'
                             ' block migrations.') % {'uuid': instance.uuid})
                    LOG.error(msg, instance=instance)
                    raise exception.MigrationPreCheckError(reason=msg)
        elif not (dest_check_data.is_shared_block_storage or
                  dest_check_data.is_shared_instance_path):
            reason = _("Shared storage live-migration requires either shared "
                       "storage or boot-from-volume with no local disks.")
            raise exception.InvalidSharedStorage(reason=reason, path=source)

        # NOTE(mikal): include the instance directory name here because it
        # doesn't yet exist on the destination but we want to force that
        # same name to be used
        instance_path = libvirt_utils.get_instance_path(instance,
                                                        relative=True)
        dest_check_data.instance_relative_path = instance_path

        return dest_check_data

    def _is_shared_block_storage(self, instance, dest_check_data,
                                 block_device_info=None):
        """Check if all block storage of an instance can be shared
        between source and destination of a live migration.

        Returns true if the instance is volume backed and has no local disks,
        or if the image backend is the same on source and destination and the
        backend shares block storage between compute nodes.

        :param instance: nova.objects.instance.Instance object
        :param dest_check_data: dict with boolean fields image_type,
                                is_shared_instance_path, and is_volume_backed
        """
        if (dest_check_data.obj_attr_is_set('image_type') and
                CONF.libvirt.images_type == dest_check_data.image_type and
                self.image_backend.backend().is_shared_block_storage()):
            # NOTE(dgenin): currently true only for RBD image backend
            return True

        if (dest_check_data.is_shared_instance_path and
                self.image_backend.backend().is_file_in_instance_path()):
            # NOTE(angdraug): file based image backends (Flat, Qcow2)
            # place block device files under the instance path
            return True

        if (dest_check_data.is_volume_backed and
                not bool(self._get_instance_disk_info(instance,
                                                      block_device_info))):
            return True

        return False

    def _assert_dest_node_has_enough_disk(self, context, instance,
                                             available_mb, disk_over_commit,
                                             block_device_info):
        """Checks if destination has enough disk for block migration."""
        # Libvirt supports qcow2 disk format,which is usually compressed
        # on compute nodes.
        # Real disk image (compressed) may enlarged to "virtual disk size",
        # that is specified as the maximum disk size.
        # (See qemu-img -f path-to-disk)
        # Scheduler recognizes destination host still has enough disk space
        # if real disk size < available disk size
        # if disk_over_commit is True,
        #  otherwise virtual disk size < available disk size.

        available = 0
        if available_mb:
            available = available_mb * units.Mi

        disk_infos = self._get_instance_disk_info(instance, block_device_info)

        necessary = 0
        if disk_over_commit:
            for info in disk_infos:
                necessary += int(info['disk_size'])
        else:
            for info in disk_infos:
                necessary += int(info['virt_disk_size'])

        # Check that available disk > necessary disk
        if (available - necessary) < 0:
            reason = (_('Unable to migrate %(instance_uuid)s: '
                        'Disk of instance is too large(available'
                        ' on destination host:%(available)s '
                        '< need:%(necessary)s)') %
                      {'instance_uuid': instance.uuid,
                       'available': available,
                       'necessary': necessary})
            raise exception.MigrationPreCheckError(reason=reason)

    def _compare_cpu(self, guest_cpu, host_cpu_str, instance):
        """Check the host is compatible with the requested CPU

        :param guest_cpu: nova.objects.VirtCPUModel or None
        :param host_cpu_str: JSON from _get_cpu_info() method

        If the 'guest_cpu' parameter is not None, this will be
        validated for migration compatibility with the host.
        Otherwise the 'host_cpu_str' JSON string will be used for
        validation.

        :returns:
            None. if given cpu info is not compatible to this server,
            raise exception.
        """

        # NOTE(kchamart): Comparing host to guest CPU model for emulated
        # guests (<domain type='qemu'>) should not matter -- in this
        # mode (QEMU "TCG") the CPU is fully emulated in software and no
        # hardware acceleration, like KVM, is involved. So, skip the CPU
        # compatibility check for the QEMU domain type, and retain it for
        # KVM guests.
        if CONF.libvirt.virt_type not in ['kvm']:
            return

        if guest_cpu is None:
            info = jsonutils.loads(host_cpu_str)
            LOG.info('Instance launched has CPU info: %s', host_cpu_str)
            cpu = vconfig.LibvirtConfigCPU()
            cpu.arch = info['arch']
            cpu.model = info['model']
            cpu.vendor = info['vendor']
            cpu.sockets = info['topology']['sockets']
            cpu.cores = info['topology']['cores']
            cpu.threads = info['topology']['threads']
            for f in info['features']:
                cpu.add_feature(vconfig.LibvirtConfigCPUFeature(f))
        else:
            cpu = self._vcpu_model_to_cpu_config(guest_cpu)

        u = ("http://libvirt.org/html/libvirt-libvirt-host.html#"
             "virCPUCompareResult")
        m = _("CPU doesn't have compatibility.\n\n%(ret)s\n\nRefer to %(u)s")
        # unknown character exists in xml, then libvirt complains
        try:
            cpu_xml = cpu.to_xml()
            LOG.debug("cpu compare xml: %s", cpu_xml, instance=instance)
            ret = self._host.compare_cpu(cpu_xml)
        except libvirt.libvirtError as e:
            error_code = e.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                LOG.debug("URI %(uri)s does not support cpu comparison. "
                          "It will be proceeded though. Error: %(error)s",
                          {'uri': self._uri(), 'error': e})
                return
            else:
                LOG.error(m, {'ret': e, 'u': u})
                raise exception.MigrationPreCheckError(
                    reason=m % {'ret': e, 'u': u})

        if ret <= 0:
            LOG.error(m, {'ret': ret, 'u': u})
            raise exception.InvalidCPUInfo(reason=m % {'ret': ret, 'u': u})

    def _create_shared_storage_test_file(self, instance):
        """Makes tmpfile under CONF.instances_path."""
        dirpath = CONF.instances_path
        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug("Creating tmpfile %s to notify to other "
                  "compute nodes that they should mount "
                  "the same storage.", tmp_file, instance=instance)
        os.close(fd)
        return os.path.basename(tmp_file)

    def _check_shared_storage_test_file(self, filename, instance):
        """Confirms existence of the tmpfile under CONF.instances_path.

        Cannot confirm tmpfile return False.
        """
        # NOTE(tpatzig): if instances_path is a shared volume that is
        # under heavy IO (many instances on many compute nodes),
        # then checking the existence of the testfile fails,
        # just because it takes longer until the client refreshes and new
        # content gets visible.
        # os.utime (like touch) on the directory forces the client to refresh.
        os.utime(CONF.instances_path, None)

        tmp_file = os.path.join(CONF.instances_path, filename)
        if not os.path.exists(tmp_file):
            exists = False
        else:
            exists = True
        LOG.debug('Check if temp file %s exists to indicate shared storage '
                  'is being used for migration. Exists? %s', tmp_file, exists,
                  instance=instance)
        return exists

    def _cleanup_shared_storage_test_file(self, filename):
        """Removes existence of the tmpfile under CONF.instances_path."""
        tmp_file = os.path.join(CONF.instances_path, filename)
        os.remove(tmp_file)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        """Ensure that an instance's filtering rules are enabled.

        When migrating an instance, we need the filtering rules to
        be configured on the destination host before starting the
        migration.

        Also, when restarting the compute service, we need to ensure
        that filtering rules exist for all running services.
        """

        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance,
                network_info)

        # nwfilters may be defined in a separate thread in the case
        # of libvirt non-blocking mode, so we wait for completion
        timeout_count = list(range(CONF.live_migration_retry_count))
        while timeout_count:
            if self.firewall_driver.instance_filter_exists(instance,
                                                           network_info):
                break
            timeout_count.pop()
            if len(timeout_count) == 0:
                msg = _('The firewall filter for %s does not exist')
                raise exception.InternalError(msg % instance.name)
            greenthread.sleep(1)

    def filter_defer_apply_on(self):
        self.firewall_driver.filter_defer_apply_on()

    def filter_defer_apply_off(self):
        self.firewall_driver.filter_defer_apply_off()

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Spawning live_migration operation for distributing high-load.

        :param context: security context
        :param instance:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param dest: destination host
        :param post_method:
            post operation method.
            expected nova.compute.manager._post_live_migration.
        :param recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager._rollback_live_migration.
        :param block_migration: if true, do block migration.
        :param migrate_data: a LibvirtLiveMigrateData object

        """

        # 'dest' will be substituted into 'migration_uri' so ensure
        # it does't contain any characters that could be used to
        # exploit the URI accepted by libivrt
        if not libvirt_utils.is_valid_hostname(dest):
            raise exception.InvalidHostname(hostname=dest)

        self._live_migration(context, instance, dest,
                             post_method, recover_method, block_migration,
                             migrate_data)

    def live_migration_abort(self, instance):
        """Aborting a running live-migration.

        :param instance: instance object that is in migration

        """

        guest = self._host.get_guest(instance)
        dom = guest._domain

        try:
            dom.abortJob()
        except libvirt.libvirtError as e:
            LOG.error("Failed to cancel migration %s", e, instance=instance)
            raise

    def _verify_serial_console_is_disabled(self):
        if CONF.serial_console.enabled:

            msg = _('Your destination node does not support'
                    ' retrieving listen addresses.  In order'
                    ' for live migration to work properly you'
                    ' must disable serial console.')
            raise exception.MigrationError(reason=msg)

    def _live_migration_operation(self, context, instance, dest,
                                  block_migration, migrate_data, guest,
                                  device_names):
        """Invoke the live migration operation

        :param context: security context
        :param instance:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param dest: destination host
        :param block_migration: if true, do block migration.
        :param migrate_data: a LibvirtLiveMigrateData object
        :param guest: the guest domain object
        :param device_names: list of device names that are being migrated with
            instance

        This method is intended to be run in a background thread and will
        block that thread until the migration is finished or failed.
        """
        try:
            if migrate_data.block_migration:
                migration_flags = self._block_migration_flags
            else:
                migration_flags = self._live_migration_flags

            serial_listen_addr = libvirt_migrate.serial_listen_addr(
                migrate_data)
            if not serial_listen_addr:
                # In this context we want to ensure that serial console is
                # disabled on source node. This is because nova couldn't
                # retrieve serial listen address from destination node, so we
                # consider that destination node might have serial console
                # disabled as well.
                self._verify_serial_console_is_disabled()

            # NOTE(aplanas) migrate_uri will have a value only in the
            # case that `live_migration_inbound_addr` parameter is
            # set, and we propose a non tunneled migration.
            migrate_uri = None
            if ('target_connect_addr' in migrate_data and
                    migrate_data.target_connect_addr is not None):
                dest = migrate_data.target_connect_addr
                if (migration_flags &
                    libvirt.VIR_MIGRATE_TUNNELLED == 0):
                    migrate_uri = self._migrate_uri(dest)

            params = None
            new_xml_str = None
            if CONF.libvirt.virt_type != "parallels":
                new_xml_str = libvirt_migrate.get_updated_guest_xml(
                    # TODO(sahid): It's not a really good idea to pass
                    # the method _get_volume_config and we should to find
                    # a way to avoid this in future.
                    guest, migrate_data, self._get_volume_config)
            if self._host.has_min_version(
                    MIN_LIBVIRT_BLOCK_LM_WITH_VOLUMES_VERSION):
                params = {
                    'destination_xml': new_xml_str,
                    'migrate_disks': device_names,
                }
                # NOTE(pkoniszewski): Because of precheck which blocks
                # tunnelled block live migration with mapped volumes we
                # can safely remove migrate_disks when tunnelling is on.
                # Otherwise we will block all tunnelled block migrations,
                # even when an instance does not have volumes mapped.
                # This is because selective disk migration is not
                # supported in tunnelled block live migration. Also we
                # cannot fallback to migrateToURI2 in this case because of
                # bug #1398999
                if (migration_flags &
                    libvirt.VIR_MIGRATE_TUNNELLED != 0):
                    params.pop('migrate_disks')

            # TODO(sahid): This should be in
            # post_live_migration_at_source but no way to retrieve
            # ports acquired on the host for the guest at this
            # step. Since the domain is going to be removed from
            # libvird on source host after migration, we backup the
            # serial ports to release them if all went well.
            serial_ports = []
            if CONF.serial_console.enabled:
                serial_ports = list(self._get_serial_ports_from_guest(guest))

            guest.migrate(self._live_migration_uri(dest),
                          migrate_uri=migrate_uri,
                          flags=migration_flags,
                          params=params,
                          domain_xml=new_xml_str,
                          bandwidth=CONF.libvirt.live_migration_bandwidth)

            for hostname, port in serial_ports:
                serial_console.release_port(host=hostname, port=port)
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error("Live Migration failure: %s", e, instance=instance)

        # If 'migrateToURI' fails we don't know what state the
        # VM instances on each host are in. Possibilities include
        #
        #  1. src==running, dst==none
        #
        #     Migration failed & rolled back, or never started
        #
        #  2. src==running, dst==paused
        #
        #     Migration started but is still ongoing
        #
        #  3. src==paused,  dst==paused
        #
        #     Migration data transfer completed, but switchover
        #     is still ongoing, or failed
        #
        #  4. src==paused,  dst==running
        #
        #     Migration data transfer completed, switchover
        #     happened but cleanup on source failed
        #
        #  5. src==none,    dst==running
        #
        #     Migration fully succeeded.
        #
        # Libvirt will aim to complete any migration operation
        # or roll it back. So even if the migrateToURI call has
        # returned an error, if the migration was not finished
        # libvirt should clean up.
        #
        # So we take the error raise here with a pinch of salt
        # and rely on the domain job info status to figure out
        # what really happened to the VM, which is a much more
        # reliable indicator.
        #
        # In particular we need to try very hard to ensure that
        # Nova does not "forget" about the guest. ie leaving it
        # running on a different host to the one recorded in
        # the database, as that would be a serious resource leak

        LOG.debug("Migration operation thread has finished",
                  instance=instance)

    def _live_migration_copy_disk_paths(self, context, instance, guest):
        '''Get list of disks to copy during migration

        :param context: security context
        :param instance: the instance being migrated
        :param guest: the Guest instance being migrated

        Get the list of disks to copy during migration.

        :returns: a list of local source paths and a list of device names to
            copy
        '''

        disk_paths = []
        device_names = []
        block_devices = []

        # TODO(pkoniszewski): Remove version check when we bump min libvirt
        # version to >= 1.2.17.
        if (self._block_migration_flags &
                libvirt.VIR_MIGRATE_TUNNELLED == 0 and
                self._host.has_min_version(
                    MIN_LIBVIRT_BLOCK_LM_WITH_VOLUMES_VERSION)):
            bdm_list = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
            block_device_info = driver.get_block_device_info(instance,
                                                             bdm_list)

            block_device_mappings = driver.block_device_info_get_mapping(
                block_device_info)
            for bdm in block_device_mappings:
                device_name = str(bdm['mount_device'].rsplit('/', 1)[1])
                block_devices.append(device_name)

        for dev in guest.get_all_disks():
            if dev.readonly or dev.shareable:
                continue
            if dev.source_type not in ["file", "block"]:
                continue
            if dev.target_dev in block_devices:
                continue
            disk_paths.append(dev.source_path)
            device_names.append(dev.target_dev)
        return (disk_paths, device_names)

    def _live_migration_data_gb(self, instance, disk_paths):
        '''Calculate total amount of data to be transferred

        :param instance: the nova.objects.Instance being migrated
        :param disk_paths: list of disk paths that are being migrated
        with instance

        Calculates the total amount of data that needs to be
        transferred during the live migration. The actual
        amount copied will be larger than this, due to the
        guest OS continuing to dirty RAM while the migration
        is taking place. So this value represents the minimal
        data size possible.

        :returns: data size to be copied in GB
        '''

        ram_gb = instance.flavor.memory_mb * units.Mi / units.Gi
        if ram_gb < 2:
            ram_gb = 2

        disk_gb = 0
        for path in disk_paths:
            try:
                size = os.stat(path).st_size
                size_gb = (size / units.Gi)
                if size_gb < 2:
                    size_gb = 2
                disk_gb += size_gb
            except OSError as e:
                LOG.warning("Unable to stat %(disk)s: %(ex)s",
                            {'disk': path, 'ex': e})
                # Ignore error since we don't want to break
                # the migration monitoring thread operation

        return ram_gb + disk_gb

    def _get_migration_flags(self, is_block_migration):
        if is_block_migration:
            return self._block_migration_flags
        return self._live_migration_flags

    def _live_migration_monitor(self, context, instance, guest,
                                dest, post_method,
                                recover_method, block_migration,
                                migrate_data, finish_event,
                                disk_paths):
        on_migration_failure = deque()
        data_gb = self._live_migration_data_gb(instance, disk_paths)
        downtime_steps = list(libvirt_migrate.downtime_steps(data_gb))
        migration = migrate_data.migration
        curdowntime = None

        migration_flags = self._get_migration_flags(
                                  migrate_data.block_migration)

        n = 0
        start = time.time()
        progress_time = start
        progress_watermark = None
        previous_data_remaining = -1
        is_post_copy_enabled = self._is_post_copy_enabled(migration_flags)
        while True:
            info = guest.get_job_info()

            if info.type == libvirt.VIR_DOMAIN_JOB_NONE:
                # Either still running, or failed or completed,
                # lets untangle the mess
                if not finish_event.ready():
                    LOG.debug("Operation thread is still running",
                              instance=instance)
                else:
                    info.type = libvirt_migrate.find_job_type(guest, instance)
                    LOG.debug("Fixed incorrect job type to be %d",
                              info.type, instance=instance)

            if info.type == libvirt.VIR_DOMAIN_JOB_NONE:
                # Migration is not yet started
                LOG.debug("Migration not running yet",
                          instance=instance)
            elif info.type == libvirt.VIR_DOMAIN_JOB_UNBOUNDED:
                # Migration is still running
                #
                # This is where we wire up calls to change live
                # migration status. eg change max downtime, cancel
                # the operation, change max bandwidth
                libvirt_migrate.run_tasks(guest, instance,
                                          self.active_migrations,
                                          on_migration_failure,
                                          migration,
                                          is_post_copy_enabled)

                now = time.time()
                elapsed = now - start

                if ((progress_watermark is None) or
                    (progress_watermark == 0) or
                    (progress_watermark > info.data_remaining)):
                    progress_watermark = info.data_remaining
                    progress_time = now

                progress_timeout = CONF.libvirt.live_migration_progress_timeout
                completion_timeout = int(
                    CONF.libvirt.live_migration_completion_timeout * data_gb)
                if libvirt_migrate.should_abort(instance, now, progress_time,
                                                progress_timeout, elapsed,
                                                completion_timeout,
                                                migration.status):
                    try:
                        guest.abort_job()
                    except libvirt.libvirtError as e:
                        LOG.warning("Failed to abort migration %s",
                                    e, instance=instance)
                        self._clear_empty_migration(instance)
                        raise

                if (is_post_copy_enabled and
                    libvirt_migrate.should_switch_to_postcopy(
                    info.memory_iteration, info.data_remaining,
                    previous_data_remaining, migration.status)):
                    libvirt_migrate.trigger_postcopy_switch(guest,
                                                            instance,
                                                            migration)
                previous_data_remaining = info.data_remaining

                curdowntime = libvirt_migrate.update_downtime(
                    guest, instance, curdowntime,
                    downtime_steps, elapsed)

                # We loop every 500ms, so don't log on every
                # iteration to avoid spamming logs for long
                # running migrations. Just once every 5 secs
                # is sufficient for developers to debug problems.
                # We log once every 30 seconds at info to help
                # admins see slow running migration operations
                # when debug logs are off.
                if (n % 10) == 0:
                    # Ignoring memory_processed, as due to repeated
                    # dirtying of data, this can be way larger than
                    # memory_total. Best to just look at what's
                    # remaining to copy and ignore what's done already
                    #
                    # TODO(berrange) perhaps we could include disk
                    # transfer stats in the progress too, but it
                    # might make memory info more obscure as large
                    # disk sizes might dwarf memory size
                    remaining = 100
                    if info.memory_total != 0:
                        remaining = round(info.memory_remaining *
                                          100 / info.memory_total)

                    libvirt_migrate.save_stats(instance, migration,
                                               info, remaining)

                    lg = LOG.debug
                    if (n % 60) == 0:
                        lg = LOG.info

                    lg("Migration running for %(secs)d secs, "
                       "memory %(remaining)d%% remaining; "
                       "(bytes processed=%(processed_memory)d, "
                       "remaining=%(remaining_memory)d, "
                       "total=%(total_memory)d)",
                       {"secs": n / 2, "remaining": remaining,
                        "processed_memory": info.memory_processed,
                        "remaining_memory": info.memory_remaining,
                        "total_memory": info.memory_total}, instance=instance)
                    if info.data_remaining > progress_watermark:
                        lg("Data remaining %(remaining)d bytes, "
                           "low watermark %(watermark)d bytes "
                           "%(last)d seconds ago",
                           {"remaining": info.data_remaining,
                            "watermark": progress_watermark,
                            "last": (now - progress_time)}, instance=instance)

                n = n + 1
            elif info.type == libvirt.VIR_DOMAIN_JOB_COMPLETED:
                # Migration is all done
                LOG.info("Migration operation has completed",
                         instance=instance)
                post_method(context, instance, dest, block_migration,
                            migrate_data)
                break
            elif info.type == libvirt.VIR_DOMAIN_JOB_FAILED:
                # Migration did not succeed
                LOG.error("Migration operation has aborted", instance=instance)
                libvirt_migrate.run_recover_tasks(self._host, guest, instance,
                                                  on_migration_failure)
                recover_method(context, instance, dest, migrate_data)
                break
            elif info.type == libvirt.VIR_DOMAIN_JOB_CANCELLED:
                # Migration was stopped by admin
                LOG.warning("Migration operation was cancelled",
                            instance=instance)
                libvirt_migrate.run_recover_tasks(self._host, guest, instance,
                                                  on_migration_failure)
                recover_method(context, instance, dest, migrate_data,
                               migration_status='cancelled')
                break
            else:
                LOG.warning("Unexpected migration job type: %d",
                            info.type, instance=instance)

            time.sleep(0.5)
        self._clear_empty_migration(instance)

    def _clear_empty_migration(self, instance):
        try:
            del self.active_migrations[instance.uuid]
        except KeyError:
            LOG.warning("There are no records in active migrations "
                        "for instance", instance=instance)

    def _live_migration(self, context, instance, dest, post_method,
                        recover_method, block_migration,
                        migrate_data):
        """Do live migration.

        :param context: security context
        :param instance:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param dest: destination host
        :param post_method:
            post operation method.
            expected nova.compute.manager._post_live_migration.
        :param recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager._rollback_live_migration.
        :param block_migration: if true, do block migration.
        :param migrate_data: a LibvirtLiveMigrateData object

        This fires off a new thread to run the blocking migration
        operation, and then this thread monitors the progress of
        migration and controls its operation
        """

        guest = self._host.get_guest(instance)

        disk_paths = []
        device_names = []
        if (migrate_data.block_migration and
                CONF.libvirt.virt_type != "parallels"):
            disk_paths, device_names = self._live_migration_copy_disk_paths(
                context, instance, guest)

        opthread = utils.spawn(self._live_migration_operation,
                                     context, instance, dest,
                                     block_migration,
                                     migrate_data, guest,
                                     device_names)

        finish_event = eventlet.event.Event()
        self.active_migrations[instance.uuid] = deque()

        def thread_finished(thread, event):
            LOG.debug("Migration operation thread notification",
                      instance=instance)
            event.send()
        opthread.link(thread_finished, finish_event)

        # Let eventlet schedule the new thread right away
        time.sleep(0)

        try:
            LOG.debug("Starting monitoring of live migration",
                      instance=instance)
            self._live_migration_monitor(context, instance, guest, dest,
                                         post_method, recover_method,
                                         block_migration, migrate_data,
                                         finish_event, disk_paths)
        except Exception as ex:
            LOG.warning("Error monitoring migration: %(ex)s",
                        {"ex": ex}, instance=instance, exc_info=True)
            raise
        finally:
            LOG.debug("Live migration monitoring is all done",
                      instance=instance)

    def _is_post_copy_enabled(self, migration_flags):
        if self._is_post_copy_available():
            if (migration_flags & libvirt.VIR_MIGRATE_POSTCOPY) != 0:
                return True
        return False

    def live_migration_force_complete(self, instance):
        try:
            self.active_migrations[instance.uuid].append('force-complete')
        except KeyError:
            raise exception.NoActiveMigrationForInstance(
                instance_id=instance.uuid)

    def _try_fetch_image(self, context, path, image_id, instance,
                         fallback_from_host=None):
        try:
            libvirt_utils.fetch_image(context, path, image_id)
        except exception.ImageNotFound:
            if not fallback_from_host:
                raise
            LOG.debug("Image %(image_id)s doesn't exist anymore on "
                      "image service, attempting to copy image "
                      "from %(host)s",
                      {'image_id': image_id, 'host': fallback_from_host})
            libvirt_utils.copy_image(src=path, dest=path,
                                     host=fallback_from_host,
                                     receive=True)

    def _fetch_instance_kernel_ramdisk(self, context, instance,
                                       fallback_from_host=None):
        """Download kernel and ramdisk for instance in instance directory."""
        instance_dir = libvirt_utils.get_instance_path(instance)
        if instance.kernel_id:
            kernel_path = os.path.join(instance_dir, 'kernel')
            # NOTE(dsanders): only fetch image if it's not available at
            # kernel_path. This also avoids ImageNotFound exception if
            # the image has been deleted from glance
            if not os.path.exists(kernel_path):
                self._try_fetch_image(context,
                                      kernel_path,
                                      instance.kernel_id,
                                      instance, fallback_from_host)
            if instance.ramdisk_id:
                ramdisk_path = os.path.join(instance_dir, 'ramdisk')
                # NOTE(dsanders): only fetch image if it's not available at
                # ramdisk_path. This also avoids ImageNotFound exception if
                # the image has been deleted from glance
                if not os.path.exists(ramdisk_path):
                    self._try_fetch_image(context,
                                          ramdisk_path,
                                          instance.ramdisk_id,
                                          instance, fallback_from_host)

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        """Clean up destination node after a failed live migration."""
        try:
            self.destroy(context, instance, network_info, block_device_info,
                         destroy_disks)
        finally:
            # NOTE(gcb): Failed block live migration may leave instance
            # directory at destination node, ensure it is always deleted.
            is_shared_instance_path = True
            if migrate_data:
                is_shared_instance_path = migrate_data.is_shared_instance_path
                if (migrate_data.obj_attr_is_set("serial_listen_ports")
                    and migrate_data.serial_listen_ports):
                    # Releases serial ports reserved.
                    for port in migrate_data.serial_listen_ports:
                        serial_console.release_port(
                            host=migrate_data.serial_listen_addr, port=port)

            if not is_shared_instance_path:
                instance_dir = libvirt_utils.get_instance_path_at_destination(
                    instance, migrate_data)
                if os.path.exists(instance_dir):
                    shutil.rmtree(instance_dir)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        """Preparation live migration."""
        if disk_info is not None:
            disk_info = jsonutils.loads(disk_info)

        LOG.debug('migrate_data in pre_live_migration: %s', migrate_data,
                  instance=instance)
        is_shared_block_storage = migrate_data.is_shared_block_storage
        is_shared_instance_path = migrate_data.is_shared_instance_path
        is_block_migration = migrate_data.block_migration

        if not is_shared_instance_path:
            instance_dir = libvirt_utils.get_instance_path_at_destination(
                            instance, migrate_data)

            if os.path.exists(instance_dir):
                raise exception.DestinationDiskExists(path=instance_dir)

            LOG.debug('Creating instance directory: %s', instance_dir,
                      instance=instance)
            os.mkdir(instance_dir)

            # Recreate the disk.info file and in doing so stop the
            # imagebackend from recreating it incorrectly by inspecting the
            # contents of each file when using the Raw backend.
            if disk_info:
                image_disk_info = {}
                for info in disk_info:
                    image_file = os.path.basename(info['path'])
                    image_path = os.path.join(instance_dir, image_file)
                    image_disk_info[image_path] = info['type']

                LOG.debug('Creating disk.info with the contents: %s',
                          image_disk_info, instance=instance)

                image_disk_info_path = os.path.join(instance_dir,
                                                    'disk.info')
                libvirt_utils.write_to_file(image_disk_info_path,
                                            jsonutils.dumps(image_disk_info))

            if not is_shared_block_storage:
                # Ensure images and backing files are present.
                LOG.debug('Checking to make sure images and backing files are '
                          'present before live migration.', instance=instance)
                self._create_images_and_backing(
                    context, instance, instance_dir, disk_info,
                    fallback_from_host=instance.host)
                if (configdrive.required_by(instance) and
                        CONF.config_drive_format == 'iso9660'):
                    # NOTE(pkoniszewski): Due to a bug in libvirt iso config
                    # drive needs to be copied to destination prior to
                    # migration when instance path is not shared and block
                    # storage is not shared. Files that are already present
                    # on destination are excluded from a list of files that
                    # need to be copied to destination. If we don't do that
                    # live migration will fail on copying iso config drive to
                    # destination and writing to read-only device.
                    # Please see bug/1246201 for more details.
                    src = "%s:%s/disk.config" % (instance.host, instance_dir)
                    self._remotefs.copy_file(src, instance_dir)

            if not is_block_migration:
                # NOTE(angdraug): when block storage is shared between source
                # and destination and instance path isn't (e.g. volume backed
                # or rbd backed instance), instance path on destination has to
                # be prepared

                # Required by Quobyte CI
                self._ensure_console_log_for_instance(instance)

                # if image has kernel and ramdisk, just download
                # following normal way.
                self._fetch_instance_kernel_ramdisk(context, instance)

        # Establishing connection to volume server.
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        if len(block_device_mapping):
            LOG.debug('Connecting volumes before live migration.',
                      instance=instance)

        for bdm in block_device_mapping:
            connection_info = bdm['connection_info']
            disk_info = blockinfo.get_info_from_bdm(
                instance, CONF.libvirt.virt_type,
                instance.image_meta, bdm)
            self._connect_volume(connection_info, disk_info, instance)

        # We call plug_vifs before the compute manager calls
        # ensure_filtering_rules_for_instance, to ensure bridge is set up
        # Retry operation is necessary because continuously request comes,
        # concurrent request occurs to iptables, then it complains.
        LOG.debug('Plugging VIFs before live migration.', instance=instance)
        max_retry = CONF.live_migration_retry_count
        for cnt in range(max_retry):
            try:
                self.plug_vifs(instance, network_info)
                break
            except processutils.ProcessExecutionError:
                if cnt == max_retry - 1:
                    raise
                else:
                    LOG.warning('plug_vifs() failed %(cnt)d. Retry up to '
                                '%(max_retry)d.',
                                {'cnt': cnt, 'max_retry': max_retry},
                                instance=instance)
                    greenthread.sleep(1)

        # Store vncserver_listen and latest disk device info
        if not migrate_data:
            migrate_data = objects.LibvirtLiveMigrateData(bdms=[])
        else:
            migrate_data.bdms = []
        # Store live_migration_inbound_addr
        migrate_data.target_connect_addr = \
            CONF.libvirt.live_migration_inbound_addr
        migrate_data.supported_perf_events = self._supported_perf_events

        migrate_data.serial_listen_ports = []
        if CONF.serial_console.enabled:
            num_ports = hardware.get_number_of_serial_ports(
                instance.flavor, instance.image_meta)
            for port in six.moves.range(num_ports):
                migrate_data.serial_listen_ports.append(
                    serial_console.acquire_port(
                        migrate_data.serial_listen_addr))

        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            if connection_info.get('serial'):
                disk_info = blockinfo.get_info_from_bdm(
                    instance, CONF.libvirt.virt_type,
                    instance.image_meta, vol)

                bdmi = objects.LibvirtLiveMigrateBDMInfo()
                bdmi.serial = connection_info['serial']
                bdmi.connection_info = connection_info
                bdmi.bus = disk_info['bus']
                bdmi.dev = disk_info['dev']
                bdmi.type = disk_info['type']
                bdmi.format = disk_info.get('format')
                bdmi.boot_index = disk_info.get('boot_index')
                migrate_data.bdms.append(bdmi)

        return migrate_data

    def _try_fetch_image_cache(self, image, fetch_func, context, filename,
                               image_id, instance, size,
                               fallback_from_host=None):
        try:
            image.cache(fetch_func=fetch_func,
                        context=context,
                        filename=filename,
                        image_id=image_id,
                        size=size)
        except exception.ImageNotFound:
            if not fallback_from_host:
                raise
            LOG.debug("Image %(image_id)s doesn't exist anymore "
                      "on image service, attempting to copy "
                      "image from %(host)s",
                      {'image_id': image_id, 'host': fallback_from_host},
                      instance=instance)

            def copy_from_host(target):
                libvirt_utils.copy_image(src=target,
                                         dest=target,
                                         host=fallback_from_host,
                                         receive=True)
            image.cache(fetch_func=copy_from_host,
                        filename=filename)

    def _create_images_and_backing(self, context, instance, instance_dir,
                                   disk_info, fallback_from_host=None):
        """:param context: security context
           :param instance:
               nova.db.sqlalchemy.models.Instance object
               instance object that is migrated.
           :param instance_dir:
               instance path to use, calculated externally to handle block
               migrating an instance with an old style instance path
           :param disk_info:
               disk info specified in _get_instance_disk_info_from_config
               (list of dicts)
           :param fallback_from_host:
               host where we can retrieve images if the glance images are
               not available.

        """

        # Virtuozzo containers don't use backing file
        if (CONF.libvirt.virt_type == "parallels" and
                instance.vm_mode == fields.VMMode.EXE):
            return

        if not disk_info:
            disk_info = []

        for info in disk_info:
            base = os.path.basename(info['path'])
            # Get image type and create empty disk image, and
            # create backing file in case of qcow2.
            instance_disk = os.path.join(instance_dir, base)
            if not info['backing_file'] and not os.path.exists(instance_disk):
                libvirt_utils.create_image(info['type'], instance_disk,
                                           info['virt_disk_size'])
            elif info['backing_file']:
                # Creating backing file follows same way as spawning instances.
                cache_name = os.path.basename(info['backing_file'])

                disk = self.image_backend.by_name(instance, instance_disk,
                                                  CONF.libvirt.images_type)
                if cache_name.startswith('ephemeral'):
                    # The argument 'size' is used by image.cache to
                    # validate disk size retrieved from cache against
                    # the instance disk size (should always return OK)
                    # and ephemeral_size is used by _create_ephemeral
                    # to build the image if the disk is not already
                    # cached.
                    disk.cache(
                        fetch_func=self._create_ephemeral,
                        fs_label=cache_name,
                        os_type=instance.os_type,
                        filename=cache_name,
                        size=info['virt_disk_size'],
                        ephemeral_size=info['virt_disk_size'] / units.Gi)
                elif cache_name.startswith('swap'):
                    inst_type = instance.get_flavor()
                    swap_mb = inst_type.swap
                    disk.cache(fetch_func=self._create_swap,
                                filename="swap_%s" % swap_mb,
                                size=swap_mb * units.Mi,
                                swap_mb=swap_mb)
                else:
                    self._try_fetch_image_cache(disk,
                                                libvirt_utils.fetch_image,
                                                context, cache_name,
                                                instance.image_ref,
                                                instance,
                                                info['virt_disk_size'],
                                                fallback_from_host)

        # if disk has kernel and ramdisk, just download
        # following normal way.
        self._fetch_instance_kernel_ramdisk(
            context, instance, fallback_from_host=fallback_from_host)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        # Disconnect from volume server
        block_device_mapping = driver.block_device_info_get_mapping(
                block_device_info)
        connector = self.get_volume_connector(instance)
        volume_api = self._volume_api
        for vol in block_device_mapping:
            # Retrieve connection info from Cinder's initialize_connection API.
            # The info returned will be accurate for the source server.
            volume_id = vol['connection_info']['serial']
            connection_info = volume_api.initialize_connection(context,
                                                               volume_id,
                                                               connector)

            # TODO(leeantho) The following multipath_id logic is temporary
            # and will be removed in the future once os-brick is updated
            # to handle multipath for drivers in a more efficient way.
            # For now this logic is needed to ensure the connection info
            # data is correct.

            # Pull out multipath_id from the bdm information. The
            # multipath_id can be placed into the connection info
            # because it is based off of the volume and will be the
            # same on the source and destination hosts.
            if 'multipath_id' in vol['connection_info']['data']:
                multipath_id = vol['connection_info']['data']['multipath_id']
                connection_info['data']['multipath_id'] = multipath_id

            disk_dev = vol['mount_device'].rpartition("/")[2]
            self._disconnect_volume(connection_info, disk_dev, instance)

    def post_live_migration_at_source(self, context, instance, network_info):
        """Unplug VIFs from networks at source.

        :param context: security context
        :param instance: instance object reference
        :param network_info: instance network information
        """
        self.unplug_vifs(instance, network_info)

    def post_live_migration_at_destination(self, context,
                                           instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :param context: security context
        :param instance:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param network_info: instance network information
        :param block_migration: if true, post operation of block_migration.
        """
        guest = self._host.get_guest(instance)

        # TODO(sahid): In Ocata we have added the migration flag
        # VIR_MIGRATE_PERSIST_DEST to libvirt, which means that the
        # guest XML is going to be set in libvirtd on destination node
        # automatically. However we do not remove that part until P*
        # because during an upgrade, to ensure migrating instances
        # from node running Newton is still going to set the guest XML
        # in libvirtd on destination node.

        # Make sure we define the migrated instance in libvirt
        xml = guest.get_xml_desc()
        self._host.write_instance_config(xml)

    def _get_instance_disk_info_from_config(self, guest_config,
                                            block_device_info):
        """Get the non-volume disk information from the domain xml

        :param LibvirtConfigGuest guest_config: the libvirt domain config
                                                for the instance
        :param dict block_device_info: block device info for BDMs
        :returns disk_info: list of dicts with keys:

          * 'type': the disk type (str)
          * 'path': the disk path (str)
          * 'virt_disk_size': the virtual disk size (int)
          * 'backing_file': backing file of a disk image (str)
          * 'disk_size': physical disk size (int)
          * 'over_committed_disk_size': virt_disk_size - disk_size or 0
        """
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        volume_devices = set()
        for vol in block_device_mapping:
            disk_dev = vol['mount_device'].rpartition("/")[2]
            volume_devices.add(disk_dev)

        disk_info = []

        if (guest_config.virt_type == 'parallels' and
                guest_config.os_type == fields.VMMode.EXE):
            node_type = 'filesystem'
        else:
            node_type = 'disk'

        for device in guest_config.devices:
            if device.root_name != node_type:
                continue
            disk_type = device.source_type
            if device.root_name == 'filesystem':
                target = device.target_dir
                if device.source_type == 'file':
                    path = device.source_file
                elif device.source_type == 'block':
                    path = device.source_dev
                else:
                    path = None
            else:
                target = device.target_dev
                path = device.source_path

            if not path:
                LOG.debug('skipping disk for %s as it does not have a path',
                          guest_config.name)
                continue

            if disk_type not in ['file', 'block']:
                LOG.debug('skipping disk because it looks like a volume', path)
                continue

            if target in volume_devices:
                LOG.debug('skipping disk %(path)s (%(target)s) as it is a '
                          'volume', {'path': path, 'target': target})
                continue

            if device.root_name == 'filesystem':
                driver_type = device.driver_type
            else:
                driver_type = device.driver_format
            # get the real disk size or
            # raise a localized error if image is unavailable
            if disk_type == 'file' and driver_type == 'ploop':
                dk_size = 0
                for dirpath, dirnames, filenames in os.walk(path):
                    for f in filenames:
                        fp = os.path.join(dirpath, f)
                        dk_size += os.path.getsize(fp)
                qemu_img_info = disk_api.get_disk_info(path)
                virt_size = qemu_img_info.virtual_size
                backing_file = libvirt_utils.get_disk_backing_file(path)
                over_commit_size = int(virt_size) - dk_size

            elif disk_type == 'file' and driver_type == 'qcow2':
                qemu_img_info = disk_api.get_disk_info(path)
                dk_size = qemu_img_info.disk_size
                virt_size = qemu_img_info.virtual_size
                backing_file = libvirt_utils.get_disk_backing_file(path)
                over_commit_size = int(virt_size) - dk_size

            elif disk_type == 'file':
                dk_size = os.stat(path).st_blocks * 512
                virt_size = os.path.getsize(path)
                backing_file = ""
                over_commit_size = 0

            elif disk_type == 'block' and block_device_info:
                dk_size = lvm.get_volume_size(path)
                virt_size = dk_size
                backing_file = ""
                over_commit_size = 0

            else:
                LOG.debug('skipping disk %(path)s (%(target)s) - unable to '
                          'determine if volume',
                          {'path': path, 'target': target})
                continue

            disk_info.append({'type': driver_type,
                              'path': path,
                              'virt_disk_size': virt_size,
                              'backing_file': backing_file,
                              'disk_size': dk_size,
                              'over_committed_disk_size': over_commit_size})
        return disk_info

    def _get_instance_disk_info(self, instance, block_device_info):
        try:
            guest = self._host.get_guest(instance)
            config = guest.get_config()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            LOG.warning('Error from libvirt while getting description of '
                        '%(instance_name)s: [Error Code %(error_code)s] '
                        '%(ex)s',
                        {'instance_name': instance.name,
                         'error_code': error_code,
                         'ex': ex},
                        instance=instance)
            raise exception.InstanceNotFound(instance_id=instance.uuid)

        return self._get_instance_disk_info_from_config(config,
                                                        block_device_info)

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        return jsonutils.dumps(
            self._get_instance_disk_info(instance, block_device_info))

    def _get_disk_over_committed_size_total(self):
        """Return total over committed disk size for all instances."""
        # Disk size that all instance uses : virtual_size - disk_size
        disk_over_committed_size = 0
        instance_domains = self._host.list_instance_domains(only_running=False)
        if not instance_domains:
            return disk_over_committed_size

        # Get all instance uuids
        instance_uuids = [dom.UUIDString() for dom in instance_domains]
        ctx = nova_context.get_admin_context()
        # Get instance object list by uuid filter
        filters = {'uuid': instance_uuids}
        # NOTE(ankit): objects.InstanceList.get_by_filters method is
        # getting called twice one is here and another in the
        # _update_available_resource method of resource_tracker. Since
        # _update_available_resource method is synchronized, there is a
        # possibility the instances list retrieved here to calculate
        # disk_over_committed_size would differ to the list you would get
        # in _update_available_resource method for calculating usages based
        # on instance utilization.
        local_instance_list = objects.InstanceList.get_by_filters(
            ctx, filters, use_slave=True)
        # Convert instance list to dictionary with instance uuid as key.
        local_instances = {inst.uuid: inst for inst in local_instance_list}

        # Get bdms by instance uuids
        bdms = objects.BlockDeviceMappingList.bdms_by_instance_uuid(
            ctx, instance_uuids)

        for dom in instance_domains:
            try:
                guest = libvirt_guest.Guest(dom)
                config = guest.get_config()

                block_device_info = None
                if guest.uuid in local_instances \
                        and (bdms and guest.uuid in bdms):
                    # Get block device info for instance
                    block_device_info = driver.get_block_device_info(
                        local_instances[guest.uuid], bdms[guest.uuid])

                disk_infos = self._get_instance_disk_info_from_config(
                    config, block_device_info)
                if not disk_infos:
                    continue

                for info in disk_infos:
                    disk_over_committed_size += int(
                        info['over_committed_disk_size'])
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                LOG.warning(
                    'Error from libvirt while getting description of '
                    '%(instance_name)s: [Error Code %(error_code)s] %(ex)s',
                    {'instance_name': guest.name,
                     'error_code': error_code,
                     'ex': ex})
            except OSError as e:
                if e.errno in (errno.ENOENT, errno.ESTALE):
                    LOG.warning('Periodic task is updating the host stat, '
                                'it is trying to get disk %(i_name)s, '
                                'but disk file was removed by concurrent '
                                'operations such as resize.',
                                {'i_name': guest.name})
                elif e.errno == errno.EACCES:
                    LOG.warning('Periodic task is updating the host stat, '
                                'it is trying to get disk %(i_name)s, '
                                'but access is denied. It is most likely '
                                'due to a VM that exists on the compute '
                                'node but is not managed by Nova.',
                                {'i_name': guest.name})
                else:
                    raise
            except exception.VolumeBDMPathNotFound as e:
                LOG.warning('Periodic task is updating the host stats, '
                            'it is trying to get disk info for %(i_name)s, '
                            'but the backing volume block device was removed '
                            'by concurrent operations such as resize. '
                            'Error: %(error)s',
                            {'i_name': guest.name, 'error': e})
            except exception.DiskNotFound:
                with excutils.save_and_reraise_exception() as err_ctxt:
                    # If the instance is undergoing a task state transition,
                    # like moving to another host or is being deleted, we
                    # should ignore this instance and move on.
                    if guest.uuid in local_instances:
                        inst = local_instances[guest.uuid]
                        if inst.task_state is not None:
                            LOG.info('Periodic task is updating the host '
                                     'stats; it is trying to get disk info '
                                     'for %(i_name)s, but the backing disk '
                                     'was removed by a concurrent operation '
                                     '(task_state=%(task_state)s)',
                                     {'i_name': guest.name,
                                      'task_state': inst.task_state},
                                     instance=inst)
                            err_ctxt.reraise = False

            # NOTE(gtt116): give other tasks a chance.
            greenthread.sleep(0)
        return disk_over_committed_size

    def unfilter_instance(self, instance, network_info):
        """See comments of same method in firewall_driver."""
        self.firewall_driver.unfilter_instance(instance,
                                               network_info=network_info)

    def get_available_nodes(self, refresh=False):
        return [self._host.get_hostname()]

    def get_host_cpu_stats(self):
        """Return the current CPU state of the host."""
        return self._host.get_cpu_stats()

    def get_host_uptime(self):
        """Returns the result of calling "uptime"."""
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def manage_image_cache(self, context, all_instances):
        """Manage the local cache of images."""
        self.image_cache_manager.update(context, all_instances)

    def _cleanup_remote_migration(self, dest, inst_base, inst_base_resize,
                                  shared_storage=False):
        """Used only for cleanup in case migrate_disk_and_power_off fails."""
        try:
            if os.path.exists(inst_base_resize):
                utils.execute('rm', '-rf', inst_base)
                utils.execute('mv', inst_base_resize, inst_base)
                if not shared_storage:
                    self._remotefs.remove_dir(dest, inst_base)
        except Exception:
            pass

    def _is_storage_shared_with(self, dest, inst_base):
        # NOTE (rmk): There are two methods of determining whether we are
        #             on the same filesystem: the source and dest IP are the
        #             same, or we create a file on the dest system via SSH
        #             and check whether the source system can also see it.
        # NOTE (drwahl): Actually, there is a 3rd way: if images_type is rbd,
        #                it will always be shared storage
        if CONF.libvirt.images_type == 'rbd':
            return True
        shared_storage = (dest == self.get_host_ip_addr())
        if not shared_storage:
            tmp_file = uuid.uuid4().hex + '.tmp'
            tmp_path = os.path.join(inst_base, tmp_file)

            try:
                self._remotefs.create_file(dest, tmp_path)
                if os.path.exists(tmp_path):
                    shared_storage = True
                    os.unlink(tmp_path)
                else:
                    self._remotefs.remove_file(dest, tmp_path)
            except Exception:
                pass
        return shared_storage

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        LOG.debug("Starting migrate_disk_and_power_off",
                   instance=instance)

        ephemerals = driver.block_device_info_get_ephemerals(block_device_info)

        # get_bdm_ephemeral_disk_size() will return 0 if the new
        # instance's requested block device mapping contain no
        # ephemeral devices. However, we still want to check if
        # the original instance's ephemeral_gb property was set and
        # ensure that the new requested flavor ephemeral size is greater
        eph_size = (block_device.get_bdm_ephemeral_disk_size(ephemerals) or
                    instance.flavor.ephemeral_gb)

        # Checks if the migration needs a disk resize down.
        root_down = flavor.root_gb < instance.flavor.root_gb
        ephemeral_down = flavor.ephemeral_gb < eph_size
        booted_from_volume = self._is_booted_from_volume(block_device_info)

        if (root_down and not booted_from_volume) or ephemeral_down:
            reason = _("Unable to resize disk down.")
            raise exception.InstanceFaultRollback(
                exception.ResizeError(reason=reason))

        # NOTE(dgenin): Migration is not implemented for LVM backed instances.
        if CONF.libvirt.images_type == 'lvm' and not booted_from_volume:
            reason = _("Migration is not supported for LVM backed instances")
            raise exception.InstanceFaultRollback(
                exception.MigrationPreCheckError(reason=reason))

        # copy disks to destination
        # rename instance dir to +_resize at first for using
        # shared storage for instance dir (eg. NFS).
        inst_base = libvirt_utils.get_instance_path(instance)
        inst_base_resize = inst_base + "_resize"
        shared_storage = self._is_storage_shared_with(dest, inst_base)

        # try to create the directory on the remote compute node
        # if this fails we pass the exception up the stack so we can catch
        # failures here earlier
        if not shared_storage:
            try:
                self._remotefs.create_dir(dest, inst_base)
            except processutils.ProcessExecutionError as e:
                reason = _("not able to execute ssh command: %s") % e
                raise exception.InstanceFaultRollback(
                    exception.ResizeError(reason=reason))

        self.power_off(instance, timeout, retry_interval)

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device'].rpartition("/")[2]
            self._disconnect_volume(connection_info, disk_dev, instance)

        disk_info = self._get_instance_disk_info(instance, block_device_info)

        try:
            utils.execute('mv', inst_base, inst_base_resize)
            # if we are migrating the instance with shared storage then
            # create the directory.  If it is a remote node the directory
            # has already been created
            if shared_storage:
                dest = None
                utils.execute('mkdir', '-p', inst_base)

            on_execute = lambda process: \
                self.job_tracker.add_job(instance, process.pid)
            on_completion = lambda process: \
                self.job_tracker.remove_job(instance, process.pid)

            for info in disk_info:
                # assume inst_base == dirname(info['path'])
                img_path = info['path']
                fname = os.path.basename(img_path)
                from_path = os.path.join(inst_base_resize, fname)

                # We will not copy over the swap disk here, and rely on
                # finish_migration to re-create it for us. This is ok because
                # the OS is shut down, and as recreating a swap disk is very
                # cheap it is more efficient than copying either locally or
                # over the network. This also means we don't have to resize it.
                if fname == 'disk.swap':
                    continue

                compression = info['type'] not in NO_COMPRESSION_TYPES
                libvirt_utils.copy_image(from_path, img_path, host=dest,
                                         on_execute=on_execute,
                                         on_completion=on_completion,
                                         compression=compression)

            # Ensure disk.info is written to the new path to avoid disks being
            # reinspected and potentially changing format.
            src_disk_info_path = os.path.join(inst_base_resize, 'disk.info')
            if os.path.exists(src_disk_info_path):
                dst_disk_info_path = os.path.join(inst_base, 'disk.info')
                libvirt_utils.copy_image(src_disk_info_path,
                                         dst_disk_info_path,
                                         host=dest, on_execute=on_execute,
                                         on_completion=on_completion)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._cleanup_remote_migration(dest, inst_base,
                                               inst_base_resize,
                                               shared_storage)

        return jsonutils.dumps(disk_info)

    def _wait_for_running(self, instance):
        state = self.get_info(instance).state

        if state == power_state.RUNNING:
            LOG.info("Instance running successfully.", instance=instance)
            raise loopingcall.LoopingCallDone()

    @staticmethod
    def _disk_raw_to_qcow2(path):
        """Converts a raw disk to qcow2."""
        path_qcow = path + '_qcow'
        utils.execute('qemu-img', 'convert', '-f', 'raw',
                      '-O', 'qcow2', path, path_qcow)
        utils.execute('mv', path_qcow, path)

    @staticmethod
    def _disk_qcow2_to_raw(path):
        """Converts a qcow2 disk to raw."""
        path_raw = path + '_raw'
        utils.execute('qemu-img', 'convert', '-f', 'qcow2',
                      '-O', 'raw', path, path_raw)
        utils.execute('mv', path_raw, path)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        LOG.debug("Starting finish_migration", instance=instance)

        block_disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                  instance,
                                                  image_meta,
                                                  block_device_info)
        # assume _create_image does nothing if a target file exists.
        # NOTE: This has the intended side-effect of fetching a missing
        # backing file.
        self._create_image(context, instance, block_disk_info['mapping'],
                           block_device_info=block_device_info,
                           ignore_bdi_for_swap=True,
                           fallback_from_host=migration.source_compute)

        # Required by Quobyte CI
        self._ensure_console_log_for_instance(instance)

        gen_confdrive = functools.partial(
            self._create_configdrive, context, instance,
            InjectionInfo(admin_pass=None, network_info=network_info,
                          files=None))

        # Convert raw disks to qcow2 if migrating to host which uses
        # qcow2 from host which uses raw.
        disk_info = jsonutils.loads(disk_info)
        for info in disk_info:
            path = info['path']
            disk_name = os.path.basename(path)

            # NOTE(mdbooth): The code below looks wrong, but is actually
            # required to prevent a security hole when migrating from a host
            # with use_cow_images=False to one with use_cow_images=True.
            # Imagebackend uses use_cow_images to select between the
            # atrociously-named-Raw and Qcow2 backends. The Qcow2 backend
            # writes to disk.info, but does not read it as it assumes qcow2.
            # Therefore if we don't convert raw to qcow2 here, a raw disk will
            # be incorrectly assumed to be qcow2, which is a severe security
            # flaw. The reverse is not true, because the atrociously-named-Raw
            # backend supports both qcow2 and raw disks, and will choose
            # appropriately between them as long as disk.info exists and is
            # correctly populated, which it is because Qcow2 writes to
            # disk.info.
            #
            # In general, we do not yet support format conversion during
            # migration. For example:
            #   * Converting from use_cow_images=True to use_cow_images=False
            #     isn't handled. This isn't a security bug, but is almost
            #     certainly buggy in other cases, as the 'Raw' backend doesn't
            #     expect a backing file.
            #   * Converting to/from lvm and rbd backends is not supported.
            #
            # This behaviour is inconsistent, and therefore undesirable for
            # users. It is tightly-coupled to implementation quirks of 2
            # out of 5 backends in imagebackend and defends against a severe
            # security flaw which is not at all obvious without deep analysis,
            # and is therefore undesirable to developers. We should aim to
            # remove it. This will not be possible, though, until we can
            # represent the storage layout of a specific instance
            # independent of the default configuration of the local compute
            # host.

            # Config disks are hard-coded to be raw even when
            # use_cow_images=True (see _get_disk_config_image_type),so don't
            # need to be converted.
            if (disk_name != 'disk.config' and
                        info['type'] == 'raw' and CONF.use_cow_images):
                self._disk_raw_to_qcow2(info['path'])

        xml = self._get_guest_xml(context, instance, network_info,
                                  block_disk_info, image_meta,
                                  block_device_info=block_device_info)
        # NOTE(mriedem): vifs_already_plugged=True here, regardless of whether
        # or not we've migrated to another host, because we unplug VIFs locally
        # and the status change in the port might go undetected by the neutron
        # L2 agent (or neutron server) so neutron may not know that the VIF was
        # unplugged in the first place and never send an event.
        guest = self._create_domain_and_network(context, xml, instance,
                                        network_info,
                                        block_device_info=block_device_info,
                                        power_on=power_on,
                                        vifs_already_plugged=True,
                                        post_xml_callback=gen_confdrive)
        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

            # Sync guest time after migration.
            guest.sync_guest_time()

        LOG.debug("finish_migration finished successfully.", instance=instance)

    def _cleanup_failed_migration(self, inst_base):
        """Make sure that a failed migrate doesn't prevent us from rolling
        back in a revert.
        """
        try:
            shutil.rmtree(inst_base)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        LOG.debug("Starting finish_revert_migration",
                  instance=instance)

        inst_base = libvirt_utils.get_instance_path(instance)
        inst_base_resize = inst_base + "_resize"

        # NOTE(danms): if we're recovering from a failed migration,
        # make sure we don't have a left-over same-host base directory
        # that would conflict. Also, don't fail on the rename if the
        # failure happened early.
        if os.path.exists(inst_base_resize):
            self._cleanup_failed_migration(inst_base)
            utils.execute('mv', inst_base_resize, inst_base)

        root_disk = self.image_backend.by_name(instance, 'disk')
        # Once we rollback, the snapshot is no longer needed, so remove it
        # TODO(nic): Remove the try/except/finally in a future release
        # To avoid any upgrade issues surrounding instances being in pending
        # resize state when the software is updated, this portion of the
        # method logs exceptions rather than failing on them.  Once it can be
        # reasonably assumed that no such instances exist in the wild
        # anymore, the try/except/finally should be removed,
        # and ignore_errors should be set back to False (the default) so
        # that problems throw errors, like they should.
        if root_disk.exists():
            try:
                root_disk.rollback_to_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)
            except exception.SnapshotNotFound:
                LOG.warning("Failed to rollback snapshot (%s)",
                            libvirt_utils.RESIZE_SNAPSHOT_NAME)
            finally:
                root_disk.remove_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME,
                                      ignore_errors=True)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            instance.image_meta,
                                            block_device_info)
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  instance.image_meta,
                                  block_device_info=block_device_info)
        self._create_domain_and_network(context, xml, instance, network_info,
                                        block_device_info=block_device_info,
                                        power_on=power_on,
                                        vifs_already_plugged=True)

        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

        LOG.debug("finish_revert_migration finished successfully.",
                  instance=instance)

    def confirm_migration(self, context, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._cleanup_resize(context, instance, network_info)

    @staticmethod
    def _get_io_devices(xml_doc):
        """get the list of io devices from the xml document."""
        result = {"volumes": [], "ifaces": []}
        try:
            doc = etree.fromstring(xml_doc)
        except Exception:
            return result
        blocks = [('./devices/disk', 'volumes'),
            ('./devices/interface', 'ifaces')]
        for block, key in blocks:
            section = doc.findall(block)
            for node in section:
                for child in node.getchildren():
                    if child.tag == 'target' and child.get('dev'):
                        result[key].append(child.get('dev'))
        return result

    def get_diagnostics(self, instance):
        guest = self._host.get_guest(instance)

        # TODO(sahid): We are converting all calls from a
        # virDomain object to use nova.virt.libvirt.Guest.
        # We should be able to remove domain at the end.
        domain = guest._domain
        output = {}
        # get cpu time, might launch an exception if the method
        # is not supported by the underlying hypervisor being
        # used by libvirt
        try:
            for vcpu in guest.get_vcpus_info():
                output["cpu" + str(vcpu.id) + "_time"] = vcpu.time
        except libvirt.libvirtError:
            pass
        # get io status
        xml = guest.get_xml_desc()
        dom_io = LibvirtDriver._get_io_devices(xml)
        for guest_disk in dom_io["volumes"]:
            try:
                # blockStats might launch an exception if the method
                # is not supported by the underlying hypervisor being
                # used by libvirt
                stats = domain.blockStats(guest_disk)
                output[guest_disk + "_read_req"] = stats[0]
                output[guest_disk + "_read"] = stats[1]
                output[guest_disk + "_write_req"] = stats[2]
                output[guest_disk + "_write"] = stats[3]
                output[guest_disk + "_errors"] = stats[4]
            except libvirt.libvirtError:
                pass
        for interface in dom_io["ifaces"]:
            try:
                # interfaceStats might launch an exception if the method
                # is not supported by the underlying hypervisor being
                # used by libvirt
                stats = domain.interfaceStats(interface)
                output[interface + "_rx"] = stats[0]
                output[interface + "_rx_packets"] = stats[1]
                output[interface + "_rx_errors"] = stats[2]
                output[interface + "_rx_drop"] = stats[3]
                output[interface + "_tx"] = stats[4]
                output[interface + "_tx_packets"] = stats[5]
                output[interface + "_tx_errors"] = stats[6]
                output[interface + "_tx_drop"] = stats[7]
            except libvirt.libvirtError:
                pass
        output["memory"] = domain.maxMemory()
        # memoryStats might launch an exception if the method
        # is not supported by the underlying hypervisor being
        # used by libvirt
        try:
            mem = domain.memoryStats()
            for key in mem.keys():
                output["memory-" + key] = mem[key]
        except (libvirt.libvirtError, AttributeError):
            pass
        return output

    def get_instance_diagnostics(self, instance):
        guest = self._host.get_guest(instance)

        # TODO(sahid): We are converting all calls from a
        # virDomain object to use nova.virt.libvirt.Guest.
        # We should be able to remove domain at the end.
        domain = guest._domain

        xml = guest.get_xml_desc()
        xml_doc = etree.fromstring(xml)

        # TODO(sahid): Needs to use get_info but more changes have to
        # be done since a mapping STATE_MAP LIBVIRT_POWER_STATE is
        # needed.
        (state, max_mem, mem, num_cpu, cpu_time) = \
            guest._get_domain_info(self._host)
        config_drive = configdrive.required_by(instance)
        launched_at = timeutils.normalize_time(instance.launched_at)
        uptime = timeutils.delta_seconds(launched_at,
                                         timeutils.utcnow())
        diags = diagnostics_obj.Diagnostics(state=power_state.STATE_MAP[state],
                                        driver='libvirt',
                                        config_drive=config_drive,
                                        hypervisor=CONF.libvirt.virt_type,
                                        hypervisor_os='linux',
                                        uptime=uptime)
        diags.memory_details = diagnostics_obj.MemoryDiagnostics(
            maximum=max_mem / units.Mi,
            used=mem / units.Mi)

        # get cpu time, might launch an exception if the method
        # is not supported by the underlying hypervisor being
        # used by libvirt
        try:
            for vcpu in guest.get_vcpus_info():
                diags.add_cpu(id=vcpu.id, time=vcpu.time)
        except libvirt.libvirtError:
            pass
        # get io status
        dom_io = LibvirtDriver._get_io_devices(xml)
        for guest_disk in dom_io["volumes"]:
            try:
                # blockStats might launch an exception if the method
                # is not supported by the underlying hypervisor being
                # used by libvirt
                stats = domain.blockStats(guest_disk)
                diags.add_disk(read_bytes=stats[1],
                               read_requests=stats[0],
                               write_bytes=stats[3],
                               write_requests=stats[2],
                               errors_count=stats[4])
            except libvirt.libvirtError:
                pass
        for interface in dom_io["ifaces"]:
            try:
                # interfaceStats might launch an exception if the method
                # is not supported by the underlying hypervisor being
                # used by libvirt
                stats = domain.interfaceStats(interface)
                diags.add_nic(rx_octets=stats[0],
                              rx_errors=stats[2],
                              rx_drop=stats[3],
                              rx_packets=stats[1],
                              tx_octets=stats[4],
                              tx_errors=stats[6],
                              tx_drop=stats[7],
                              tx_packets=stats[5])
            except libvirt.libvirtError:
                pass

        # Update mac addresses of interface if stats have been reported
        if diags.nic_details:
            nodes = xml_doc.findall('./devices/interface/mac')
            for index, node in enumerate(nodes):
                diags.nic_details[index].mac_address = node.get('address')
        return diags

    @staticmethod
    def _prepare_device_bus(dev):
        """Determines the device bus and its hypervisor assigned address
        """
        bus = None
        address = (dev.device_addr.format_address() if
                   dev.device_addr else None)
        if isinstance(dev.device_addr,
                      vconfig.LibvirtConfigGuestDeviceAddressPCI):
            bus = objects.PCIDeviceBus()
        elif isinstance(dev, vconfig.LibvirtConfigGuestDisk):
            if dev.target_bus == 'scsi':
                bus = objects.SCSIDeviceBus()
            elif dev.target_bus == 'ide':
                bus = objects.IDEDeviceBus()
            elif dev.target_bus == 'usb':
                bus = objects.USBDeviceBus()
        if address is not None and bus is not None:
            bus.address = address
        return bus

    def _build_interface_metadata(self, dev, vifs_to_expose, vlans_by_mac):
        """Builds a metadata object for a network interface

        :param dev: The LibvirtConfigGuestInterface to build metadata for.
        :param vifs_to_expose: The list of tagged and/or vlan'ed
                               VirtualInterface objects.
        :param vlans_by_mac: A dictionary of mac address -> vlan associations.
        :return: A NetworkInterfaceMetadata object, or None.
        """
        vif = vifs_to_expose.get(dev.mac_addr)
        if not vif:
            LOG.debug('No VIF found with MAC %s, not building metadata',
                      dev.mac_addr)
            return None
        bus = self._prepare_device_bus(dev)
        device = objects.NetworkInterfaceMetadata(mac=vif.address)
        if 'tag' in vif and vif.tag:
            device.tags = [vif.tag]
        if bus:
            device.bus = bus
        vlan = vlans_by_mac.get(vif.address)
        if vlan:
            device.vlan = int(vlan)
        return device

    def _build_disk_metadata(self, dev, tagged_bdms):
        """Builds a metadata object for a disk

        :param dev: The vconfig.LibvirtConfigGuestDisk to build metadata for.
        :param tagged_bdms: The list of tagged BlockDeviceMapping objects.
        :return: A DiskMetadata object, or None.
        """
        bdm = tagged_bdms.get(dev.target_dev)
        if not bdm:
            LOG.debug('No BDM found with device name %s, not building '
                      'metadata.', dev.target_dev)
            return None
        bus = self._prepare_device_bus(dev)
        device = objects.DiskMetadata(tags=[bdm.tag])
        # NOTE(artom) Setting the serial (which corresponds to
        # volume_id in BlockDeviceMapping) in DiskMetadata allows us to
        # find the disks's BlockDeviceMapping object when we detach the
        # volume and want to clean up its metadata.
        device.serial = bdm.volume_id
        if bus:
            device.bus = bus
        return device

    def _build_hostdev_metadata(self, dev, vifs_to_expose, vlans_by_mac):
        """Builds a metadata object for a hostdev. This can only be a PF, so we
        don't need trusted_by_mac like in _build_interface_metadata because
        only VFs can be trusted.

        :param dev: The LibvirtConfigGuestHostdevPCI to build metadata for.
        :param vifs_to_expose: The list of tagged and/or vlan'ed
                               VirtualInterface objects.
        :param vlans_by_mac: A dictionary of mac address -> vlan associations.
        :return: A NetworkInterfaceMetadata object, or None.
        """
        # Strip out the leading '0x'
        pci_address = pci_utils.get_pci_address(
            *[x[2:] for x in (dev.domain, dev.bus, dev.slot, dev.function)])
        try:
            mac = pci_utils.get_mac_by_pci_address(pci_address,
                                                   pf_interface=True)
        except exception.PciDeviceNotFoundById:
            LOG.debug('Not exposing metadata for not found PCI device %s',
                      pci_address)
            return None

        vif = vifs_to_expose.get(mac)
        if not vif:
            LOG.debug('No VIF found with MAC %s, not building metadata', mac)
            return None

        device = objects.NetworkInterfaceMetadata(mac=mac)
        device.bus = objects.PCIDeviceBus(address=pci_address)
        if 'tag' in vif and vif.tag:
            device.tags = [vif.tag]
        vlan = vlans_by_mac.get(mac)
        if vlan:
            device.vlan = int(vlan)
        return device

    def _build_device_metadata(self, context, instance):
        """Builds a metadata object for instance devices, that maps the user
           provided tag to the hypervisor assigned device address.
        """
        def _get_device_name(bdm):
            return block_device.strip_dev(bdm.device_name)

        network_info = instance.info_cache.network_info
        vlans_by_mac = netutils.get_cached_vifs_with_vlan(network_info)
        vifs = objects.VirtualInterfaceList.get_by_instance_uuid(context,
                                                                 instance.uuid)
        vifs_to_expose = {vif.address: vif for vif in vifs
                          if ('tag' in vif and vif.tag) or
                             vlans_by_mac.get(vif.address)}
        # TODO(mriedem): We should be able to avoid the DB query here by using
        # block_device_info['block_device_mapping'] which is passed into most
        # methods that call this function.
        bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
            context, instance.uuid)
        tagged_bdms = {_get_device_name(bdm): bdm for bdm in bdms if bdm.tag}

        devices = []
        guest = self._host.get_guest(instance)
        xml = guest.get_xml_desc()
        xml_dom = etree.fromstring(xml)
        guest_config = vconfig.LibvirtConfigGuest()
        guest_config.parse_dom(xml_dom)

        for dev in guest_config.devices:
            device = None
            if isinstance(dev, vconfig.LibvirtConfigGuestInterface):
                device = self._build_interface_metadata(dev, vifs_to_expose,
                                                        vlans_by_mac)
            if isinstance(dev, vconfig.LibvirtConfigGuestDisk):
                device = self._build_disk_metadata(dev, tagged_bdms)
            if isinstance(dev, vconfig.LibvirtConfigGuestHostdevPCI):
                device = self._build_hostdev_metadata(dev, vifs_to_expose,
                                                      vlans_by_mac)
            if device:
                devices.append(device)
        if devices:
            dev_meta = objects.InstanceDeviceMetadata(devices=devices)
            return dev_meta

    def instance_on_disk(self, instance):
        # ensure directories exist and are writable
        instance_path = libvirt_utils.get_instance_path(instance)
        LOG.debug('Checking instance files accessibility %s', instance_path,
                  instance=instance)
        shared_instance_path = os.access(instance_path, os.W_OK)
        # NOTE(flwang): For shared block storage scenario, the file system is
        # not really shared by the two hosts, but the volume of evacuated
        # instance is reachable.
        shared_block_storage = (self.image_backend.backend().
                                is_shared_block_storage())
        return shared_instance_path or shared_block_storage

    def inject_network_info(self, instance, nw_info):
        self.firewall_driver.setup_basic_filtering(instance, nw_info)

    def delete_instance_files(self, instance):
        target = libvirt_utils.get_instance_path(instance)
        # A resize may be in progress
        target_resize = target + '_resize'
        # Other threads may attempt to rename the path, so renaming the path
        # to target + '_del' (because it is atomic) and iterating through
        # twice in the unlikely event that a concurrent rename occurs between
        # the two rename attempts in this method. In general this method
        # should be fairly thread-safe without these additional checks, since
        # other operations involving renames are not permitted when the task
        # state is not None and the task state should be set to something
        # other than None by the time this method is invoked.
        target_del = target + '_del'
        for i in range(2):
            try:
                utils.execute('mv', target, target_del)
                break
            except Exception:
                pass
            try:
                utils.execute('mv', target_resize, target_del)
                break
            except Exception:
                pass
        # Either the target or target_resize path may still exist if all
        # rename attempts failed.
        remaining_path = None
        for p in (target, target_resize):
            if os.path.exists(p):
                remaining_path = p
                break

        # A previous delete attempt may have been interrupted, so target_del
        # may exist even if all rename attempts during the present method
        # invocation failed due to the absence of both target and
        # target_resize.
        if not remaining_path and os.path.exists(target_del):
            self.job_tracker.terminate_jobs(instance)

            LOG.info('Deleting instance files %s', target_del,
                     instance=instance)
            remaining_path = target_del
            try:
                shutil.rmtree(target_del)
            except OSError as e:
                LOG.error('Failed to cleanup directory %(target)s: %(e)s',
                          {'target': target_del, 'e': e}, instance=instance)

        # It is possible that the delete failed, if so don't mark the instance
        # as cleaned.
        if remaining_path and os.path.exists(remaining_path):
            LOG.info('Deletion of %s failed', remaining_path,
                     instance=instance)
            return False

        LOG.info('Deletion of %s complete', target_del, instance=instance)
        return True

    @property
    def need_legacy_block_device_info(self):
        return False

    def default_root_device_name(self, instance, image_meta, root_bdm):
        disk_bus = blockinfo.get_disk_bus_for_device_type(
            instance, CONF.libvirt.virt_type, image_meta, "disk")
        cdrom_bus = blockinfo.get_disk_bus_for_device_type(
            instance, CONF.libvirt.virt_type, image_meta, "cdrom")
        root_info = blockinfo.get_root_info(
            instance, CONF.libvirt.virt_type, image_meta,
            root_bdm, disk_bus, cdrom_bus)
        return block_device.prepend_dev(root_info['dev'])

    def default_device_names_for_instance(self, instance, root_device_name,
                                          *block_device_lists):
        block_device_mapping = list(itertools.chain(*block_device_lists))
        # NOTE(ndipanov): Null out the device names so that blockinfo code
        #                 will assign them
        for bdm in block_device_mapping:
            if bdm.device_name is not None:
                LOG.warning(
                    "Ignoring supplied device name: %(device_name)s. "
                    "Libvirt can't honour user-supplied dev names",
                    {'device_name': bdm.device_name}, instance=instance)
                bdm.device_name = None
        block_device_info = driver.get_block_device_info(instance,
                                                         block_device_mapping)

        blockinfo.default_device_names(CONF.libvirt.virt_type,
                                       nova_context.get_admin_context(),
                                       instance,
                                       block_device_info,
                                       instance.image_meta)

    def get_device_name_for_instance(self, instance, bdms, block_device_obj):
        block_device_info = driver.get_block_device_info(instance, bdms)
        instance_info = blockinfo.get_disk_info(
                CONF.libvirt.virt_type, instance,
                instance.image_meta, block_device_info=block_device_info)

        suggested_dev_name = block_device_obj.device_name
        if suggested_dev_name is not None:
            LOG.warning(
                'Ignoring supplied device name: %(suggested_dev)s',
                {'suggested_dev': suggested_dev_name}, instance=instance)

        # NOTE(ndipanov): get_info_from_bdm will generate the new device name
        #                 only when it's actually not set on the bd object
        block_device_obj.device_name = None
        disk_info = blockinfo.get_info_from_bdm(
            instance, CONF.libvirt.virt_type, instance.image_meta,
            block_device_obj, mapping=instance_info['mapping'])
        return block_device.prepend_dev(disk_info['dev'])

    def is_supported_fs_format(self, fs_type):
        return fs_type in [disk_api.FS_FORMAT_EXT2, disk_api.FS_FORMAT_EXT3,
                           disk_api.FS_FORMAT_EXT4, disk_api.FS_FORMAT_XFS]
