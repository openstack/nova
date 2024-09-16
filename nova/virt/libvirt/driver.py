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

Supports KVM, LXC, QEMU, and Parallels.
"""

import binascii
import collections
from collections import deque
import contextlib
import copy
import errno
import functools
import glob
import grp
import itertools
import operator
import os
import pwd
import random
import shutil
import sys
import tempfile
import threading
import time
import typing as ty
import uuid

from castellan import key_manager
from copy import deepcopy
import eventlet
from eventlet import greenthread
from eventlet import tpool
from lxml import etree
from os_brick import encryptors
from os_brick.encryptors import luks as luks_encryptor
from os_brick import exception as brick_exception
from os_brick.initiator import connector
import os_resource_classes as orc
import os_traits as ot
from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_serialization import base64
from oslo_serialization import jsonutils
from oslo_service import loopingcall
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import fileutils
from oslo_utils import importutils
from oslo_utils import netutils as oslo_netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import units
from oslo_utils import uuidutils

from nova.api.metadata import base as instance_metadata
from nova.api.metadata import password
from nova import block_device
from nova.compute import power_state
from nova.compute import provider_tree
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
import nova.conf
from nova.console import serial as serial_console
from nova.console import type as ctype
from nova import context as nova_context
from nova import crypto
from nova.db import constants as db_const
from nova import exception
from nova.i18n import _
from nova.image import glance
from nova.network import model as network_model
from nova.network import neutron
from nova import objects
from nova.objects import diagnostics as diagnostics_obj
from nova.objects import fields
from nova.objects import migrate_data as migrate_data_obj
from nova.pci import manager as pci_manager
from nova.pci import utils as pci_utils
import nova.privsep.libvirt
import nova.privsep.path
import nova.privsep.utils
from nova.storage import rbd_utils
from nova import utils
from nova import version
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt.disk import api as disk_api
from nova.virt.disk.vfs import guestfs
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import hardware
from nova.virt.image import model as imgmodel
from nova.virt import images
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import designer
from nova.virt.libvirt import event as libvirtevent
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import host
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import instancejobtracker
from nova.virt.libvirt import migration as libvirt_migrate
from nova.virt.libvirt.storage import dmcrypt
from nova.virt.libvirt.storage import lvm
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt import vif as libvirt_vif
from nova.virt.libvirt.volume import fs
from nova.virt.libvirt.volume import mount
from nova.virt.libvirt.volume import remotefs
from nova.virt.libvirt.volume import volume
from nova.virt import netutils
from nova.volume import cinder

libvirt: ty.Any = None

uefi_logged = False

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF

MAX_CONSOLE_BYTES = 100 * units.Ki
VALID_DISK_CACHEMODES = [
    "default", "none", "writethrough", "writeback", "directsync", "unsafe",
]

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


# NOTE(lyarwood): Dict of volume drivers supported by the libvirt driver, keyed
# by the connection_info['driver_volume_type'] returned by Cinder for each
# volume type it supports
# TODO(lyarwood): Add host configurables to allow this list to be changed.
# Allowing native iSCSI to be reintroduced etc.
VOLUME_DRIVERS = {
    'iscsi': 'nova.virt.libvirt.volume.iscsi.LibvirtISCSIVolumeDriver',
    'iser': 'nova.virt.libvirt.volume.iser.LibvirtISERVolumeDriver',
    'local': 'nova.virt.libvirt.volume.volume.LibvirtVolumeDriver',
    'fake': 'nova.virt.libvirt.volume.volume.LibvirtFakeVolumeDriver',
    'rbd': 'nova.virt.libvirt.volume.net.LibvirtNetVolumeDriver',
    'nfs': 'nova.virt.libvirt.volume.nfs.LibvirtNFSVolumeDriver',
    'smbfs': 'nova.virt.libvirt.volume.smbfs.LibvirtSMBFSVolumeDriver',
    'fibre_channel': 'nova.virt.libvirt.volume.fibrechannel.LibvirtFibreChannelVolumeDriver',  # noqa:E501
    'gpfs': 'nova.virt.libvirt.volume.gpfs.LibvirtGPFSVolumeDriver',
    'quobyte': 'nova.virt.libvirt.volume.quobyte.LibvirtQuobyteVolumeDriver',
    'scaleio': 'nova.virt.libvirt.volume.scaleio.LibvirtScaleIOVolumeDriver',
    'vzstorage': 'nova.virt.libvirt.volume.vzstorage.LibvirtVZStorageVolumeDriver',  # noqa:E501
    'storpool': 'nova.virt.libvirt.volume.storpool.LibvirtStorPoolVolumeDriver',  # noqa:E501
    'nvmeof': 'nova.virt.libvirt.volume.nvme.LibvirtNVMEVolumeDriver',
}


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

# For information about when MIN_{LIBVIRT,QEMU}_VERSION and
# NEXT_MIN_{LIBVIRT,QEMU}_VERSION can be changed, consult the following:
#
# doc/source/reference/libvirt-distro-support-matrix.rst
#
# DO NOT FORGET to update this document when touching any versions below!
MIN_LIBVIRT_VERSION = (6, 0, 0)
MIN_QEMU_VERSION = (4, 2, 0)
NEXT_MIN_LIBVIRT_VERSION = (7, 0, 0)
NEXT_MIN_QEMU_VERSION = (5, 2, 0)

MIN_LIBVIRT_AARCH64_CPU_COMPARE = (6, 9, 0)

# Virtuozzo driver support
MIN_VIRTUOZZO_VERSION = (7, 0, 0)


# Names of the types that do not get compressed during migration
NO_COMPRESSION_TYPES = ('qcow2',)


# number of serial console limit
QEMU_MAX_SERIAL_PORTS = 4
# Qemu supports 4 serial consoles, we remove 1 because of the PTY one defined
ALLOWED_QEMU_SERIAL_PORTS = QEMU_MAX_SERIAL_PORTS - 1

VGPU_RESOURCE_SEMAPHORE = 'vgpu_resources'

LIBVIRT_PERF_EVENT_PREFIX = 'VIR_PERF_PARAM_'

# VDPA interface support
MIN_LIBVIRT_VDPA = (6, 9, 0)
MIN_QEMU_VDPA = (5, 1, 0)

REGISTER_IMAGE_PROPERTY_DEFAULTS = [
    'hw_machine_type',
    'hw_cdrom_bus',
    'hw_disk_bus',
    'hw_input_bus',
    'hw_pointer_model',
    'hw_video_model',
    'hw_vif_model',
]


class AsyncDeviceEventsHandler:
    """A synchornization point between libvirt events an clients waiting for
    such events.

    It provides an interface for the clients to wait for one or more libvirt
    event types. It implements event delivery by expecting the libvirt driver
    to forward libvirt specific events to notify_waiters()

    It handles multiple clients for the same instance, device and event
    type and delivers the event to each clients.
    """

    class Waiter:
        def __init__(
            self,
            instance_uuid: str,
            device_name: str,
            event_types: ty.Set[ty.Type[libvirtevent.DeviceEvent]]
        ):
            self.instance_uuid = instance_uuid
            self.device_name = device_name
            self.event_types = event_types
            self.threading_event = threading.Event()
            self.result: ty.Optional[libvirtevent.DeviceEvent] = None

        def matches(self, event: libvirtevent.DeviceEvent) -> bool:
            """Returns true if the event is one of the expected event types
            for the given instance and device.
            """
            return (
                self.instance_uuid == event.uuid and
                self.device_name == event.dev and
                isinstance(event, tuple(self.event_types)))

        def __repr__(self) -> str:
            return (
                "AsyncDeviceEventsHandler.Waiter("
                f"instance_uuid={self.instance_uuid}, "
                f"device_name={self.device_name}, "
                f"event_types={self.event_types})")

    def __init__(self):
        self._lock = threading.Lock()
        # Ongoing device operations in libvirt where we wait for the events
        # about success or failure.
        self._waiters: ty.Set[AsyncDeviceEventsHandler.Waiter] = set()

    def create_waiter(
        self,
        instance_uuid: str,
        device_name: str,
        event_types: ty.Set[ty.Type[libvirtevent.DeviceEvent]]
    ) -> 'AsyncDeviceEventsHandler.Waiter':
        """Returns an opaque token the caller can use in wait() to
        wait for the libvirt event

        :param instance_uuid: The UUID of the instance.
        :param device_name: The device name alias used by libvirt for this
            device.
        :param event_type: A set of classes derived from DeviceEvent
            specifying which event types the caller waits for. Specifying more
            than one event type means waiting for either of the events to be
            received.
        :returns: an opaque token to be used with wait_for_event().
        """
        waiter = AsyncDeviceEventsHandler.Waiter(
            instance_uuid, device_name, event_types)
        with self._lock:
            self._waiters.add(waiter)

        return waiter

    def delete_waiter(self, token: 'AsyncDeviceEventsHandler.Waiter'):
        """Deletes the waiter

        :param token: the opaque token returned by create_waiter() to be
            deleted
        """
        with self._lock:
            self._waiters.remove(token)

    def wait(
        self, token: 'AsyncDeviceEventsHandler.Waiter', timeout: float,
    ) -> ty.Optional[libvirtevent.DeviceEvent]:
        """Blocks waiting for the libvirt event represented by the opaque token

        :param token: A token created by calling create_waiter()
        :param timeout: Maximum number of seconds this call blocks waiting for
            the event to be received
        :returns: The received libvirt event, or None in case of timeout
        """
        token.threading_event.wait(timeout)

        with self._lock:
            self._waiters.remove(token)

        return token.result

    def notify_waiters(self, event: libvirtevent.DeviceEvent) -> bool:
        """Unblocks the client waiting for this event.

        :param event: the libvirt event that is received
        :returns: True if there was a client waiting and False otherwise.
        """
        dispatched = False
        with self._lock:
            for waiter in self._waiters:
                if waiter.matches(event):
                    waiter.result = event
                    waiter.threading_event.set()
                    dispatched = True

        return dispatched

    def cleanup_waiters(self, instance_uuid: str) -> None:
        """Deletes all waiters and unblock all clients related to the specific
        instance.

        param instance_uuid: The instance UUID for which the cleanup is
            requested
        """
        with self._lock:
            instance_waiters = set()
            for waiter in self._waiters:
                if waiter.instance_uuid == instance_uuid:
                    # unblock any waiting thread
                    waiter.threading_event.set()
                    instance_waiters.add(waiter)

            self._waiters -= instance_waiters

        if instance_waiters:
            LOG.debug(
                'Cleaned up device related libvirt event waiters: %s',
                instance_waiters)


class LibvirtDriver(driver.ComputeDriver):
    def __init__(self, virtapi, read_only=False):
        # NOTE(aspiers) Some of these are dynamic, so putting
        # capabilities on the instance rather than on the class.
        # This prevents the risk of one test setting a capability
        # which bleeds over into other tests.

        # LVM and RBD require raw images. If we are not configured to
        # force convert images into raw format, then we _require_ raw
        # images only.
        raw_only = ('rbd', 'lvm')
        requires_raw_image = (CONF.libvirt.images_type in raw_only and
                              not CONF.force_raw_images)
        requires_ploop_image = CONF.libvirt.virt_type == 'parallels'

        self.capabilities = {
            "has_imagecache": True,
            "resource_scheduling": False,
            "supports_evacuate": True,
            "supports_migrate_to_same_host": False,
            "supports_attach_interface": True,
            "supports_device_tagging": True,
            "supports_tagged_attach_interface": True,
            "supports_tagged_attach_volume": True,
            "supports_extend_volume": True,
            "supports_multiattach": True,
            "supports_trusted_certs": True,
            # Supported image types
            "supports_image_type_aki": True,
            "supports_image_type_ari": True,
            "supports_image_type_ami": True,
            "supports_image_type_raw": True,
            "supports_image_type_iso": True,
            # NOTE(danms): Certain backends do not work with complex image
            # formats. If we are configured for those backends, then we
            # should not expose the corresponding support traits.
            "supports_image_type_qcow2": not requires_raw_image,
            "supports_image_type_ploop": requires_ploop_image,
            "supports_pcpus": True,
            "supports_accelerators": True,
            "supports_bfv_rescue": True,
            "supports_vtpm": CONF.libvirt.swtpm_enabled,
            "supports_socket_pci_numa_affinity": True,
            "driver_specific_device_name": True,
        }
        super(LibvirtDriver, self).__init__(virtapi)

        if not sys.platform.startswith('linux'):
            raise exception.InternalError(
                _('The libvirt driver only works on Linux'))

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')
            libvirt_migrate.libvirt = libvirt

        self._host = host.Host(self._uri(), read_only,
                               lifecycle_event_handler=self.emit_event,
                               conn_event_handler=self._handle_conn_event)
        self._supported_perf_events = []

        self.vif_driver = libvirt_vif.LibvirtGenericVIFDriver(self._host)

        # NOTE(lyarwood): Volume drivers are loaded on-demand
        self.volume_drivers: ty.Dict[str, volume.LibvirtBaseVolumeDriver] = {}

        self._disk_cachemode = None
        self.image_cache_manager = imagecache.ImageCacheManager()
        self.image_backend = imagebackend.Backend(CONF.use_cow_images)

        self.disk_cachemodes = {}

        for mode_str in CONF.libvirt.disk_cachemodes:
            disk_type, sep, cache_mode = mode_str.partition('=')
            if cache_mode not in VALID_DISK_CACHEMODES:
                LOG.warning('Invalid cachemode %(cache_mode)s specified '
                            'for disk type %(disk_type)s.',
                            {'cache_mode': cache_mode, 'disk_type': disk_type})
                continue
            self.disk_cachemodes[disk_type] = cache_mode

        self._volume_api = cinder.API()
        self._image_api = glance.API()
        self._network_api = neutron.API()

        # The default choice for the sysinfo_serial config option is "unique"
        # which does not have a special function since the value is just the
        # instance.uuid.
        sysinfo_serial_funcs = {
            'none': lambda: None,
            'hardware': self._get_host_sysinfo_serial_hardware,
            'os': self._get_host_sysinfo_serial_os,
            'auto': self._get_host_sysinfo_serial_auto,
        }

        self._sysinfo_serial_func = sysinfo_serial_funcs.get(
            CONF.libvirt.sysinfo_serial, lambda: None)

        self.job_tracker = instancejobtracker.InstanceJobTracker()
        self._remotefs = remotefs.RemoteFilesystem()

        self._live_migration_flags = self._block_migration_flags = 0
        self.active_migrations = {}

        # Compute reserved hugepages from conf file at the very
        # beginning to ensure any syntax error will be reported and
        # avoid any re-calculation when computing resources.
        self._reserved_hugepages = hardware.numa_get_reserved_huge_pages()

        # Copy of the compute service ProviderTree object that is updated
        # every time update_provider_tree() is called.
        # NOTE(sbauza): We only want a read-only cache, this attribute is not
        # intended to be updatable directly
        self.provider_tree: provider_tree.ProviderTree = None

        # driver traits will not change during the runtime of the agent
        # so calcuate them once and save them
        self._static_traits = None

        # The CPU models in the configuration are case-insensitive, but the CPU
        # model in the libvirt is case-sensitive, therefore create a mapping to
        # map the lower case CPU model name to normal CPU model name.
        self.cpu_models_mapping = {}
        self.cpu_model_flag_mapping = {}

        self._vpmems_by_name, self._vpmems_by_rc = self._discover_vpmems(
                vpmem_conf=CONF.libvirt.pmem_namespaces)

        # We default to not support vGPUs unless the configuration is set.
        self.pgpu_type_mapping = collections.defaultdict(str)
        # This dict is for knowing which mdev class is supported by a specific
        # PCI device like we do (the key being the PCI address and the value
        # the mdev class)
        self.mdev_class_mapping: ty.Dict[str, str] = (
            collections.defaultdict(lambda: orc.VGPU)
        )
        # This set is for knowing all the mdev classes the operator provides
        self.mdev_classes = set([])
        self.supported_vgpu_types = self._get_supported_vgpu_types()

        # Handles ongoing device manipultion in libvirt where we wait for the
        # events about success or failure.
        self._device_event_handler = AsyncDeviceEventsHandler()

    def _discover_vpmems(self, vpmem_conf=None):
        """Discover vpmems on host and configuration.

        :param vpmem_conf: pmem namespaces configuration from CONF
        :returns: a dict of vpmem keyed by name, and
                  a dict of vpmem list keyed by resource class
        :raises: exception.InvalidConfiguration if Libvirt or QEMU version
                 does not meet requirement.
        """
        if not vpmem_conf:
            return {}, {}

        # vpmem keyed by name {name: objects.LibvirtVPMEMDevice,...}
        vpmems_by_name: ty.Dict[str, 'objects.LibvirtVPMEMDevice'] = {}
        # vpmem list keyed by resource class
        # {'RC_0': [objects.LibvirtVPMEMDevice, ...], 'RC_1': [...]}
        vpmems_by_rc: ty.Dict[str, ty.List['objects.LibvirtVPMEMDevice']] = (
            collections.defaultdict(list)
        )

        vpmems_host = self._get_vpmems_on_host()
        for ns_conf in vpmem_conf:
            try:
                ns_label, ns_names = ns_conf.split(":", 1)
            except ValueError:
                reason = _("The configuration doesn't follow the format")
                raise exception.PMEMNamespaceConfigInvalid(
                        reason=reason)
            ns_names = ns_names.split("|")
            for ns_name in ns_names:
                if ns_name not in vpmems_host:
                    reason = _("The PMEM namespace %s isn't on host") % ns_name
                    raise exception.PMEMNamespaceConfigInvalid(
                            reason=reason)
                if ns_name in vpmems_by_name:
                    reason = (_("Duplicated PMEM namespace %s configured") %
                                ns_name)
                    raise exception.PMEMNamespaceConfigInvalid(
                            reason=reason)
                pmem_ns_updated = vpmems_host[ns_name]
                pmem_ns_updated.label = ns_label
                vpmems_by_name[ns_name] = pmem_ns_updated
                rc = orc.normalize_name(
                        "PMEM_NAMESPACE_%s" % ns_label)
                vpmems_by_rc[rc].append(pmem_ns_updated)

        return vpmems_by_name, vpmems_by_rc

    def _get_vpmems_on_host(self):
        """Get PMEM namespaces on host using ndctl utility."""
        try:
            output = nova.privsep.libvirt.get_pmem_namespaces()
        except Exception as e:
            reason = _("Get PMEM namespaces by ndctl utility, "
                    "please ensure ndctl is installed: %s") % e
            raise exception.GetPMEMNamespacesFailed(reason=reason)

        if not output:
            return {}
        namespaces = jsonutils.loads(output)
        vpmems_host = {}  # keyed by namespace name
        for ns in namespaces:
            # store namespace info parsed from ndctl utility return
            if not ns.get('name'):
                # The name is used to identify namespaces, it's optional
                # config when creating namespace. If an namespace don't have
                # name, it can not be used by Nova, we will skip it.
                continue
            vpmems_host[ns['name']] = objects.LibvirtVPMEMDevice(
                name=ns['name'],
                devpath= '/dev/' + ns['daxregion']['devices'][0]['chardev'],
                size=ns['size'],
                align=ns['daxregion']['align'])
        return vpmems_host

    @property
    def disk_cachemode(self):
        # It can be confusing to understand the QEMU cache mode
        # behaviour, because each cache=$MODE is a convenient shorthand
        # to toggle _three_ cache.* booleans.  Consult the below table
        # (quoting from the QEMU man page):
        #
        #              | cache.writeback | cache.direct | cache.no-flush
        # --------------------------------------------------------------
        # writeback    | on              | off          | off
        # none         | on              | on           | off
        # writethrough | off             | off          | off
        # directsync   | off             | on           | off
        # unsafe       | on              | off          | on
        #
        # Where:
        #
        #  - 'cache.writeback=off' means: QEMU adds an automatic fsync()
        #    after each write request.
        #
        #  - 'cache.direct=on' means: Use Linux's O_DIRECT, i.e. bypass
        #    the kernel page cache.  Caches in any other layer (disk
        #    cache, QEMU metadata caches, etc.) can still be present.
        #
        #  - 'cache.no-flush=on' means: Ignore flush requests, i.e.
        #    never call fsync(), even if the guest explicitly requested
        #    it.
        #
        # Use cache mode "none" (cache.writeback=on, cache.direct=on,
        # cache.no-flush=off) for consistent performance and
        # migration correctness.  Some filesystems don't support
        # O_DIRECT, though.  For those we fallback to the next
        # reasonable option that is "writeback" (cache.writeback=on,
        # cache.direct=off, cache.no-flush=off).

        if self._disk_cachemode is None:
            self._disk_cachemode = "none"
            if not nova.privsep.utils.supports_direct_io(CONF.instances_path):
                self._disk_cachemode = "writeback"
        return self._disk_cachemode

    def _set_cache_mode(self, conf):
        """Set cache mode on LibvirtConfigGuestDisk object."""
        try:
            source_type = conf.source_type
            driver_cache = conf.driver_cache
        except AttributeError:
            return

        # Shareable disks like for a multi-attach volume need to have the
        # driver cache disabled.
        if getattr(conf, 'shareable', False):
            conf.driver_cache = 'none'
        else:
            cache_mode = self.disk_cachemodes.get(source_type,
                                                  driver_cache)
            conf.driver_cache = cache_mode

        # NOTE(acewit): If the [libvirt]disk_cachemodes is set as
        # `block=writeback` or `block=writethrough` or `block=unsafe`,
        # whose correponding Linux's IO semantic is not O_DIRECT in
        # file nova.conf, then it will result in an attachment failure
        # because of the libvirt bug
        # (https://bugzilla.redhat.com/show_bug.cgi?id=1086704)
        if ((getattr(conf, 'driver_io', None) == "native") and
                conf.driver_cache not in [None, 'none', 'directsync']):
            conf.driver_io = "threads"
            LOG.warning("The guest disk driver io mode has fallen back "
                        "from 'native' to 'threads' because the "
                        "disk cache mode is set as %(cachemode)s, which does "
                        "not use O_DIRECT. See the following bug report "
                        "for more details: https://launchpad.net/bugs/1841363",
                        {'cachemode': conf.driver_cache})

    def _do_quality_warnings(self):
        """Warn about potential configuration issues.

        This will log a warning message for things such as untested driver or
        host arch configurations in order to indicate potential issues to
        administrators.
        """
        if CONF.libvirt.virt_type not in ('qemu', 'kvm'):
            LOG.warning(
                "Support for the '%(type)s' libvirt backend has been "
                "deprecated and will be removed in a future release.",
                {'type': CONF.libvirt.virt_type},
            )

        caps = self._host.get_capabilities()
        hostarch = caps.host.cpu.arch
        if hostarch not in (
            fields.Architecture.I686, fields.Architecture.X86_64,
        ):
            LOG.warning(
                'The libvirt driver is not tested on %(arch)s by the '
                'OpenStack project and thus its quality can not be ensured. '
                'For more information, see: https://docs.openstack.org/'
                'nova/latest/user/support-matrix.html',
                {'arch': hostarch},
            )

    def _handle_conn_event(self, enabled, reason):
        LOG.info("Connection event '%(enabled)d' reason '%(reason)s'",
                 {'enabled': enabled, 'reason': reason})
        self._set_host_enabled(enabled, reason)

    def init_host(self, host):
        self._host.initialize()

        self._update_host_specific_capabilities()

        self._check_cpu_set_configuration()

        self._do_quality_warnings()

        self._parse_migration_flags()

        self._supported_perf_events = self._get_supported_perf_events()

        self._check_file_backed_memory_support()

        self._check_my_ip()

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
                libvirt_utils.version_to_string(MIN_LIBVIRT_VERSION))

        if CONF.libvirt.virt_type in ("qemu", "kvm"):
            if not self._host.has_min_version(hv_ver=MIN_QEMU_VERSION):
                raise exception.InternalError(
                    _('Nova requires QEMU version %s or greater.') %
                    libvirt_utils.version_to_string(MIN_QEMU_VERSION))

        if CONF.libvirt.virt_type == 'parallels':
            if not self._host.has_min_version(hv_ver=MIN_VIRTUOZZO_VERSION):
                raise exception.InternalError(
                    _('Nova requires Virtuozzo version %s or greater.') %
                    libvirt_utils.version_to_string(MIN_VIRTUOZZO_VERSION))

        # Give the cloud admin a heads up if we are intending to
        # change the MIN_LIBVIRT_VERSION in the next release.
        if not self._host.has_min_version(NEXT_MIN_LIBVIRT_VERSION):
            LOG.warning('Running Nova with a libvirt version less than '
                        '%(version)s is deprecated. The required minimum '
                        'version of libvirt will be raised to %(version)s '
                        'in the next release.',
                        {'version': libvirt_utils.version_to_string(
                            NEXT_MIN_LIBVIRT_VERSION)})
        if (CONF.libvirt.virt_type in ("qemu", "kvm") and
            not self._host.has_min_version(hv_ver=NEXT_MIN_QEMU_VERSION)):
            LOG.warning('Running Nova with a QEMU version less than '
                        '%(version)s is deprecated. The required minimum '
                        'version of QEMU will be raised to %(version)s '
                        'in the next release.',
                        {'version': libvirt_utils.version_to_string(
                            NEXT_MIN_QEMU_VERSION)})

        # Allowing both "tunnelling via libvirtd" (which will be
        # deprecated once the MIN_{LIBVIRT,QEMU}_VERSION is sufficiently
        # new enough) and "native TLS" options at the same time is
        # nonsensical.
        if (CONF.libvirt.live_migration_tunnelled and
                CONF.libvirt.live_migration_with_native_tls):
            msg = _("Setting both 'live_migration_tunnelled' and "
                    "'live_migration_with_native_tls' at the same "
                    "time is invalid. If you have the relevant "
                    "libvirt and QEMU versions, and TLS configured "
                    "in your environment, pick "
                    "'live_migration_with_native_tls'.")
            raise exception.Invalid(msg)

        # Some imagebackends are only able to import raw disk images,
        # and will fail if given any other format. See the bug
        # https://bugs.launchpad.net/nova/+bug/1816686 for more details.
        if CONF.libvirt.images_type in ('rbd',):
            if not CONF.force_raw_images:
                msg = _("'[DEFAULT]/force_raw_images = False' is not "
                        "allowed with '[libvirt]/images_type = rbd'. "
                        "Please check the two configs and if you really "
                        "do want to use rbd as images_type, set "
                        "force_raw_images to True.")
                raise exception.InvalidConfiguration(msg)

        # TODO(sbauza): Remove this code once mediated devices are persisted
        # across reboots.
        self._recreate_assigned_mediated_devices()

        self._check_cpu_compatibility()

        self._check_vtpm_support()

        # Set REGISTER_IMAGE_PROPERTY_DEFAULTS in the instance system_metadata
        # to default values for properties that have not already been set.
        self._register_all_undefined_instance_details()

    def _update_host_specific_capabilities(self) -> None:
        """Update driver capabilities based on capabilities of the host."""
        # TODO(stephenfin): We should also be reporting e.g. SEV functionality
        # or UEFI bootloader support in this manner
        self.capabilities.update({
            'supports_secure_boot': self._host.supports_secure_boot,
        })

    def _register_all_undefined_instance_details(self) -> None:
        """Register the default image properties of instances on this host

        For each instance found on this host by InstanceList.get_by_host ensure
        REGISTER_IMAGE_PROPERTY_DEFAULTS are registered within the system
        metadata of the instance
        """
        context = nova_context.get_admin_context()
        hostname = self._host.get_hostname()
        for instance in objects.InstanceList.get_by_host(
            context, hostname, expected_attrs=['flavor', 'system_metadata']
        ):
            try:
                self._register_undefined_instance_details(context, instance)
            except Exception:
                LOG.exception('Ignoring unknown failure while attempting '
                              'to save the defaults for unregistered image '
                              'properties', instance=instance)

    def _register_undefined_instance_details(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ) -> None:
        # Find any unregistered image properties against this instance
        unregistered_image_props = [
            p for p in REGISTER_IMAGE_PROPERTY_DEFAULTS
            if f"image_{p}" not in instance.system_metadata
        ]

        # Return if there's nothing left to register for this instance
        if not unregistered_image_props:
            return

        LOG.debug(f'Attempting to register defaults for the following '
                  f'image properties: {unregistered_image_props}',
                  instance=instance)

        # NOTE(lyarwood): Only build disk_info once per instance if we need it
        # for hw_{disk,cdrom}_bus to avoid pulling bdms from the db etc.
        requires_disk_info = ['hw_disk_bus', 'hw_cdrom_bus']
        disk_info = None
        if set(requires_disk_info) & set(unregistered_image_props):
            bdms = objects.BlockDeviceMappingList.get_by_instance_uuid(
                context, instance.uuid)
            block_device_info = driver.get_block_device_info(instance, bdms)
            disk_info = blockinfo.get_disk_info(
                CONF.libvirt.virt_type, instance, instance.image_meta,
                block_device_info)

        # Only pull the guest config once per instance if we need it for
        # hw_pointer_model or hw_input_bus.
        requires_guest_config = ['hw_pointer_model', 'hw_input_bus']
        guest_config = None
        if set(requires_guest_config) & set(unregistered_image_props):
            guest_config = self._host.get_guest(instance).get_config()

        for image_prop in unregistered_image_props:
            try:
                default_value = self._find_default_for_image_property(
                    instance, image_prop, disk_info, guest_config)
                instance.system_metadata[f"image_{image_prop}"] = default_value

                LOG.debug(f'Found default for {image_prop} of {default_value}',
                          instance=instance)
            except Exception:
                LOG.exception(f'Ignoring unknown failure while attempting '
                              f'to find the default of {image_prop}',
                              instance=instance)
        instance.save()

    def _find_default_for_image_property(
        self,
        instance: 'objects.Instance',
        image_property: str,
        disk_info: ty.Optional[ty.Dict[str, ty.Any]],
        guest_config: ty.Optional[vconfig.LibvirtConfigGuest],
    ) -> ty.Optional[str]:
        if image_property == 'hw_machine_type':
            return libvirt_utils.get_machine_type(instance.image_meta)

        if image_property == 'hw_disk_bus' and disk_info:
            return disk_info.get('disk_bus')

        if image_property == 'hw_cdrom_bus' and disk_info:
            return disk_info.get('cdrom_bus')

        if image_property == 'hw_input_bus' and guest_config:
            _, default_input_bus = self._get_pointer_bus_and_model(
                guest_config, instance.image_meta)
            return default_input_bus

        if image_property == 'hw_pointer_model' and guest_config:
            default_pointer_model, _ = self._get_pointer_bus_and_model(
                guest_config, instance.image_meta)
            # hw_pointer_model is of type PointerModelType ('usbtablet' instead
            # of 'tablet')
            if default_pointer_model == 'tablet':
                default_pointer_model = 'usbtablet'
            return default_pointer_model

        if image_property == 'hw_video_model':
            return self._get_video_type(instance.image_meta)

        if image_property == 'hw_vif_model':
            return self.vif_driver.get_vif_model(instance.image_meta)

        return None

    def _prepare_cpu_flag(self, flag):
        # NOTE(kchamart) This helper method will be used while computing
        # guest CPU compatibility.  It will take into account a
        # comma-separated list of CPU flags from
        # `[libvirt]cpu_model_extra_flags`.  If the CPU flag starts
        # with '+', it is enabled for the guest; if it starts with '-',
        # it is disabled.  If neither '+' nor '-' is specified, the CPU
        # flag is enabled.
        if flag.startswith('-'):
            flag = flag.lstrip('-')
            policy_value = 'disable'
        else:
            flag = flag.lstrip('+')
            policy_value = 'require'

        cpu_feature = vconfig.LibvirtConfigGuestCPUFeature(
                        flag, policy=policy_value)
        return cpu_feature

    def _check_cpu_compatibility(self):
        mode = CONF.libvirt.cpu_mode
        models = CONF.libvirt.cpu_models

        if (CONF.libvirt.virt_type not in ("kvm", "qemu") and
                mode not in (None, 'none')):
            msg = _("Config requested an explicit CPU model, but "
                    "the current libvirt hypervisor '%s' does not "
                    "support selecting CPU models") % CONF.libvirt.virt_type
            raise exception.Invalid(msg)

        if mode != "custom":
            if not models:
                return
            msg = _("The cpu_models option is not required when "
                    "cpu_mode!=custom")
            raise exception.Invalid(msg)

        if not models:
            msg = _("The cpu_models option is required when cpu_mode=custom")
            raise exception.Invalid(msg)

        if not CONF.workarounds.skip_cpu_compare_at_startup:
            # Use guest CPU model to check the compatibility between
            # guest CPU and configured extra_flags
            for model in models:
                cpu = vconfig.LibvirtConfigGuestCPU()
                cpu.model = self._get_cpu_model_mapping(model)
                for flag in set(x.lower() for
                                x in CONF.libvirt.cpu_model_extra_flags):
                    cpu_feature = self._prepare_cpu_flag(flag)
                    cpu.add_feature(cpu_feature)
                try:
                    self._compare_cpu(cpu, self._get_cpu_info(), None)
                except exception.InvalidCPUInfo as e:
                    msg = (_("Configured CPU model: %(model)s "
                             "and CPU Flags %(flags)s ar not "
                             "compatible with host CPU. Please correct your "
                             "config and try again. %(e)s") % {
                                'model': model, 'e': e,
                                'flags': CONF.libvirt.cpu_model_extra_flags})
                    raise exception.InvalidCPUInfo(msg)

    def _check_vtpm_support(self) -> None:
        # TODO(efried): A key manager must be configured to create/retrieve
        # secrets. Is there a way to check that one is set up correctly?
        # CONF.key_manager.backend is optional :(
        if not CONF.libvirt.swtpm_enabled:
            return

        if CONF.libvirt.virt_type not in ('qemu', 'kvm'):
            msg = _(
                "vTPM support requires '[libvirt] virt_type' of 'qemu' or "
                "'kvm'; found '%s'.")
            raise exception.InvalidConfiguration(msg % CONF.libvirt.virt_type)

        # These executables need to be installed for libvirt to make use of
        # emulated TPM.
        # NOTE(stephenfin): This checks using the PATH of the user running
        # nova-compute rather than the libvirtd service, meaning it's an
        # imperfect check but the best we can do
        if not any(shutil.which(cmd) for cmd in ('swtpm_setup', 'swtpm')):
            msg = _(
                "vTPM support is configured but the 'swtpm' and "
                "'swtpm_setup' binaries could not be found on PATH.")
            raise exception.InvalidConfiguration(msg)

        # The user and group must be valid on this host for cold migration and
        # resize to function.
        try:
            pwd.getpwnam(CONF.libvirt.swtpm_user)
        except KeyError:
            msg = _(
                "The user configured in '[libvirt] swtpm_user' does not exist "
                "on this host; expected '%s'.")
            raise exception.InvalidConfiguration(msg % CONF.libvirt.swtpm_user)

        try:
            grp.getgrnam(CONF.libvirt.swtpm_group)
        except KeyError:
            msg = _(
                "The group configured in '[libvirt] swtpm_group' does not "
                "exist on this host; expected '%s'.")
            raise exception.InvalidConfiguration(
                msg % CONF.libvirt.swtpm_group)

        LOG.debug('Enabling emulated TPM support')

    @staticmethod
    def _is_existing_mdev(uuid):
        # FIXME(sbauza): Some kernel can have a uevent race meaning that the
        # libvirt daemon won't know when a mediated device is created unless
        # you restart that daemon. Until all kernels we support are not having
        # that possible race, check the sysfs directly instead of asking the
        # libvirt API.
        # See https://bugzilla.redhat.com/show_bug.cgi?id=1376907 for ref.
        return os.path.exists('/sys/bus/mdev/devices/{0}'.format(uuid))

    def _recreate_assigned_mediated_devices(self):
        """Recreate assigned mdevs that could have disappeared if we reboot
        the host.
        """
        # NOTE(sbauza): This method just calls sysfs to recreate mediated
        # devices by looking up existing guest XMLs and doesn't use
        # the Placement API so it works with or without a vGPU reshape.
        mdevs = self._get_all_assigned_mediated_devices()
        for (mdev_uuid, instance_uuid) in mdevs.items():
            if not self._is_existing_mdev(mdev_uuid):
                dev_name = libvirt_utils.mdev_uuid2name(mdev_uuid)
                dev_info = self._get_mediated_device_information(dev_name)
                parent = dev_info['parent']
                parent_type = self._get_vgpu_type_per_pgpu(parent)
                if dev_info['type'] != parent_type:
                    # NOTE(sbauza): The mdev was created by using a different
                    # vGPU type. We can't recreate the mdev until the operator
                    # modifies the configuration.
                    parent = "{}:{}:{}.{}".format(*parent[4:].split('_'))
                    msg = ("The instance UUID %(inst)s uses a mediated device "
                           "type %(type)s that is no longer supported by the "
                           "parent PCI device, %(parent)s. Please correct "
                           "the configuration accordingly." %
                           {'inst': instance_uuid,
                            'parent': parent,
                            'type': dev_info['type']})
                    raise exception.InvalidLibvirtMdevConfig(reason=msg)
                self._create_new_mediated_device(parent, uuid=mdev_uuid)

    def _check_file_backed_memory_support(self):
        if not CONF.libvirt.file_backed_memory:
            return

        # file_backed_memory is only compatible with qemu/kvm virts
        if CONF.libvirt.virt_type not in ("qemu", "kvm"):
            raise exception.InternalError(
                _('Running Nova with file_backed_memory and virt_type '
                  '%(type)s is not supported. file_backed_memory is only '
                  'supported with qemu and kvm types.') %
                {'type': CONF.libvirt.virt_type})

        # file-backed memory doesn't work with memory overcommit.
        # Block service startup if file-backed memory is enabled and
        # ram_allocation_ratio is not 1.0
        if CONF.ram_allocation_ratio != 1.0:
            raise exception.InternalError(
                'Running Nova with file_backed_memory requires '
                'ram_allocation_ratio configured to 1.0')

        if CONF.reserved_host_memory_mb:
            # this is a hard failure as placement won't allow total < reserved
            if CONF.reserved_host_memory_mb >= CONF.libvirt.file_backed_memory:
                msg = _(
                    "'[libvirt] file_backed_memory', which represents total "
                    "memory reported to placement, must be greater than "
                    "reserved memory configured via '[DEFAULT] "
                    "reserved_host_memory_mb'"
                )
                raise exception.InternalError(msg)

            # TODO(stephenfin): Change this to an exception in W or later
            LOG.warning(
                "Reserving memory via '[DEFAULT] reserved_host_memory_mb' "
                "is not compatible with file-backed memory. Consider "
                "setting '[DEFAULT] reserved_host_memory_mb' to 0. This will "
                "be an error in a future release."
            )

    def _check_my_ip(self):
        ips = compute_utils.get_machine_ips()
        if CONF.my_ip not in ips:
            LOG.warning('my_ip address (%(my_ip)s) was not found on '
                        'any of the interfaces: %(ifaces)s',
                        {'my_ip': CONF.my_ip, 'ifaces': ", ".join(ips)})

    def _check_cpu_set_configuration(self):
        # evaluate these now to force a quick fail if they're invalid
        vcpu_pin_set = hardware.get_vcpu_pin_set() or set()
        cpu_shared_set = hardware.get_cpu_shared_set() or set()
        cpu_dedicated_set = hardware.get_cpu_dedicated_set() or set()

        # TODO(stephenfin): Remove this in U once we remove the 'vcpu_pin_set'
        # option
        if not vcpu_pin_set:
            if not (cpu_shared_set or cpu_dedicated_set):
                return

            if not cpu_dedicated_set.isdisjoint(cpu_shared_set):
                msg = _(
                    "The '[compute] cpu_dedicated_set' and '[compute] "
                    "cpu_shared_set' configuration options must be "
                    "disjoint.")
                raise exception.InvalidConfiguration(msg)

            if CONF.reserved_host_cpus:
                msg = _(
                    "The 'reserved_host_cpus' config option cannot be defined "
                    "alongside the '[compute] cpu_shared_set' or '[compute] "
                    "cpu_dedicated_set' options. Unset 'reserved_host_cpus'.")
                raise exception.InvalidConfiguration(msg)

            return

        if cpu_dedicated_set:
            # NOTE(stephenfin): This is a new option in Train so it can be
            # an error
            msg = _(
                "The 'vcpu_pin_set' config option has been deprecated and "
                "cannot be defined alongside '[compute] cpu_dedicated_set'. "
                "Unset 'vcpu_pin_set'.")
            raise exception.InvalidConfiguration(msg)

        if cpu_shared_set:
            LOG.warning(
                "The '[compute] cpu_shared_set' and 'vcpu_pin_set' config "
                "options have both been defined. While 'vcpu_pin_set' is "
                "defined, it will continue to be used to configure the "
                "specific host CPUs used for 'VCPU' inventory, while "
                "'[compute] cpu_shared_set' will only be used for guest "
                "emulator threads when 'hw:emulator_threads_policy=shared' "
                "is defined in the flavor. This is legacy behavior and will "
                "not be supported in a future release. "
                "If you wish to define specific host CPUs to be used for "
                "'VCPU' or 'PCPU' inventory, you must migrate the "
                "'vcpu_pin_set' config option value to '[compute] "
                "cpu_shared_set' and '[compute] cpu_dedicated_set', "
                "respectively, and undefine 'vcpu_pin_set'.")
        else:
            LOG.warning(
                "The 'vcpu_pin_set' config option has been deprecated and "
                "will be removed in a future release. When defined, "
                "'vcpu_pin_set' will be used to calculate 'VCPU' inventory "
                "and schedule instances that have 'VCPU' allocations. "
                "If you wish to define specific host CPUs to be used for "
                "'VCPU' or 'PCPU' inventory, you must migrate the "
                "'vcpu_pin_set' config option value to '[compute] "
                "cpu_shared_set' and '[compute] cpu_dedicated_set', "
                "respectively, and undefine 'vcpu_pin_set'.")

    def _prepare_migration_flags(self):
        migration_flags = 0

        migration_flags |= libvirt.VIR_MIGRATE_LIVE

        # Enable support for p2p migrations
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

    # TODO(kchamart) Once the MIN_LIBVIRT_VERSION and MIN_QEMU_VERSION
    # reach 4.4.0 and 2.11.0, which provide "native TLS" support by
    # default, deprecate and remove the support for "tunnelled live
    # migration" (and related config attribute), because:
    #
    #  (a) it cannot handle live migration of disks in a non-shared
    #      storage setup (a.k.a. "block migration");
    #
    #  (b) has a huge performance overhead and latency, because it burns
    #      more CPU and memory bandwidth due to increased number of data
    #      copies on both source and destination hosts.
    #
    # Both the above limitations are addressed by the QEMU-native TLS
    # support (`live_migration_with_native_tls`).
    def _handle_live_migration_tunnelled(self, migration_flags):
        if CONF.libvirt.live_migration_tunnelled:
            migration_flags |= libvirt.VIR_MIGRATE_TUNNELLED
        return migration_flags

    def _handle_native_tls(self, migration_flags):
        if (CONF.libvirt.live_migration_with_native_tls):
            migration_flags |= libvirt.VIR_MIGRATE_TLS
        return migration_flags

    def _handle_live_migration_post_copy(self, migration_flags):
        if CONF.libvirt.live_migration_permit_post_copy:
            migration_flags |= libvirt.VIR_MIGRATE_POSTCOPY
        return migration_flags

    def _handle_live_migration_auto_converge(self, migration_flags):
        if self._is_post_copy_enabled(migration_flags):
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

        live_migration_flags = self._handle_native_tls(
            live_migration_flags)
        block_migration_flags = self._handle_native_tls(
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
        if CONF.libvirt.virt_type == 'lxc':
            uri = CONF.libvirt.connection_uri or 'lxc:///'
        elif CONF.libvirt.virt_type == 'parallels':
            uri = CONF.libvirt.connection_uri or 'parallels:///system'
        else:
            uri = CONF.libvirt.connection_uri or 'qemu:///system'
        return uri

    @staticmethod
    def _live_migration_uri(dest):
        uris = {
            'kvm': 'qemu+%(scheme)s://%(dest)s/system',
            'qemu': 'qemu+%(scheme)s://%(dest)s/system',
            'parallels': 'parallels+tcp://%(dest)s/system',
        }
        dest = oslo_netutils.escape_ipv6(dest)

        virt_type = CONF.libvirt.virt_type
        # TODO(pkoniszewski): Remove fetching live_migration_uri in Pike
        uri = CONF.libvirt.live_migration_uri
        if uri:
            return uri % dest

        uri = uris.get(virt_type)
        if uri is None:
            raise exception.LiveMigrationURINotAvailable(virt_type=virt_type)

        str_format = {
            'dest': dest,
            'scheme': CONF.libvirt.live_migration_scheme or 'tcp',
        }
        return uri % str_format

    @staticmethod
    def _migrate_uri(dest):
        uri = None
        dest = oslo_netutils.escape_ipv6(dest)

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

    def _destroy(self, instance):
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
                    with excutils.save_and_reraise_exception():
                        LOG.warning("Cannot destroy instance, general system "
                                    "call failure", instance=instance)
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
                new_domid = dom_info.internal_id
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
                destroy_disks=True, destroy_secrets=True):
        self._destroy(instance)
        # NOTE(gibi): if there was device detach in progress then we need to
        # unblock the waiting threads and clean up.
        self._device_event_handler.cleanup_waiters(instance.uuid)
        self.cleanup(context, instance, network_info, block_device_info,
                     destroy_disks, destroy_secrets=destroy_secrets)

    def _undefine_domain(self, instance):
        try:
            guest = self._host.get_guest(instance)
            try:
                hw_firmware_type = instance.image_meta.properties.get(
                    'hw_firmware_type')
                support_uefi = self._check_uefi_support(hw_firmware_type)
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
                                  {'errcode': errcode,
                                   'e': encodeutils.exception_to_unicode(e)},
                                  instance=instance)
        except exception.InstanceNotFound:
            pass

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True,
                destroy_secrets=True):
        """Cleanup the instance from the host.

        Identify if the instance disks and instance path should be removed
        from the host before calling down into the _cleanup method for the
        actual removal of resources from the host.

        :param context: security context
        :param instance: instance object for the instance being cleaned up
        :param network_info: instance network information
        :param block_device_info: optional instance block device information
        :param destroy_disks: if local ephemeral disks should be destroyed
        :param migrate_data: optional migrate_data object
        :param destroy_vifs: if plugged vifs should be unplugged
        :param destroy_secrets: Indicates if secrets should be destroyed
        """
        cleanup_instance_dir = False
        cleanup_instance_disks = False
        # We assume destroy_disks means destroy instance directory and disks
        if destroy_disks:
            cleanup_instance_dir = True
            cleanup_instance_disks = True
        else:
            # NOTE(mdbooth): I think the theory here was that if this is a
            # migration with shared block storage then we need to delete the
            # instance directory because that's not shared. I'm pretty sure
            # this is wrong.
            if migrate_data and 'is_shared_block_storage' in migrate_data:
                cleanup_instance_dir = migrate_data.is_shared_block_storage

            # NOTE(lyarwood): The following workaround allows operators to
            # ensure that non-shared instance directories are removed after an
            # evacuation or revert resize when using the shared RBD
            # imagebackend. This workaround is not required when cleaning up
            # migrations that provide migrate_data to this method as the
            # existing is_shared_block_storage conditional will cause the
            # instance directory to be removed.
            if not cleanup_instance_dir:
                if CONF.workarounds.ensure_libvirt_rbd_instance_dir_cleanup:
                    cleanup_instance_dir = CONF.libvirt.images_type == 'rbd'

        return self._cleanup(
                context, instance, network_info,
                block_device_info=block_device_info,
                destroy_vifs=destroy_vifs,
                cleanup_instance_dir=cleanup_instance_dir,
                cleanup_instance_disks=cleanup_instance_disks,
                destroy_secrets=destroy_secrets)

    def _cleanup(self, context, instance, network_info, block_device_info=None,
                 destroy_vifs=True, cleanup_instance_dir=False,
                 cleanup_instance_disks=False, destroy_secrets=True):
        """Cleanup the domain and any attached resources from the host.

        This method cleans up any pmem devices, unplugs VIFs, disconnects
        attached volumes and undefines the instance domain within libvirt.
        It also optionally removes the ephemeral disks and the instance
        directory from the host depending on the cleanup_instance_dir|disks
        kwargs provided.

        :param context: security context
        :param instance: instance object for the instance being cleaned up
        :param network_info: instance network information
        :param block_device_info: optional instance block device information
        :param destroy_vifs: if plugged vifs should be unplugged
        :param cleanup_instance_dir: If the instance dir should be removed
        :param cleanup_instance_disks: If the instance disks should be removed
        """
        # zero the data on backend pmem device
        vpmems = self._get_vpmems(instance)
        if vpmems:
            self._cleanup_vpmems(vpmems)

        if destroy_vifs:
            self._unplug_vifs(instance, network_info, True)

        # FIXME(wangpan): if the instance is booted again here, such as the
        #                 soft reboot operation boot it here, it will become
        #                 "running deleted", should we check and destroy it
        #                 at the end of this method?

        # NOTE(vish): we disconnect from volumes regardless
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            if not connection_info:
                # if booting from a volume, creation could have failed meaning
                # this would be unset
                continue

            try:
                self._disconnect_volume(
                    context, connection_info, instance,
                    destroy_secrets=destroy_secrets)
            except Exception as exc:
                with excutils.save_and_reraise_exception() as ctxt:
                    if cleanup_instance_disks:
                        # Don't block on Volume errors if we're trying to
                        # delete the instance as we may be partially created
                        # or deleted
                        ctxt.reraise = False
                        LOG.warning(
                            "Ignoring Volume Error on vol %(vol_id)s "
                            "during delete %(exc)s",
                            {'vol_id': vol.get('volume_id'),
                             'exc': encodeutils.exception_to_unicode(exc)},
                            instance=instance)

        if cleanup_instance_disks:
            # NOTE(haomai): destroy volumes if needed
            if CONF.libvirt.images_type == 'lvm':
                self._cleanup_lvm(instance, block_device_info)
            if CONF.libvirt.images_type == 'rbd':
                self._cleanup_rbd(instance)

        if cleanup_instance_dir:
            attempts = int(instance.system_metadata.get('clean_attempts',
                                                        '0'))
            success = self.delete_instance_files(instance)
            # NOTE(mriedem): This is used in the _run_pending_deletes periodic
            # task in the compute manager. The tight coupling is not great...
            instance.system_metadata['clean_attempts'] = str(attempts + 1)
            if success:
                instance.cleaned = True
            try:
                instance.save()
            except exception.InstanceNotFound:
                pass

        if cleanup_instance_disks:
            crypto.delete_vtpm_secret(context, instance)

        self._undefine_domain(instance)

    def cleanup_lingering_instance_resources(self, instance):
        # zero the data on backend pmem device, if fails
        # it will raise an exception
        vpmems = self._get_vpmems(instance)
        if vpmems:
            self._cleanup_vpmems(vpmems)

    def _cleanup_vpmems(self, vpmems):
        for vpmem in vpmems:
            try:
                nova.privsep.libvirt.cleanup_vpmem(vpmem.devpath)
            except Exception as e:
                raise exception.VPMEMCleanupFailed(dev=vpmem.devpath,
                                                   error=e)

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

    def _get_scsi_controller_next_unit(self, guest):
        """Returns the max disk unit used by scsi controller"""
        xml = guest.get_xml_desc()
        tree = etree.fromstring(xml)
        addrs = "./devices/disk[target/@bus='scsi']/address[@type='drive']"

        ret = []
        for obj in tree.xpath(addrs):
            ret.append(int(obj.get('unit', 0)))
        return max(ret) + 1 if ret else 0

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
        rbd_utils.RBDDriver().cleanup_volumes(filter_fn)

    def _cleanup_lvm(self, instance, block_device_info):
        """Delete all LVM disks for given instance object."""
        if instance.get('ephemeral_key_uuid') is not None:
            # detach encrypted volumes
            disks = self._get_instance_disk_info(instance, block_device_info)
            for disk in disks:
                if dmcrypt.is_encrypted(disk['path']):
                    dmcrypt.delete_volume(disk['path'])

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

    def _cleanup_resize_vtpm(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ) -> None:
        """Handle vTPM when confirming a migration or resize.

        If the old flavor have vTPM and the new one doesn't, there are keys to
        be deleted.
        """
        old_vtpm_config = hardware.get_vtpm_constraint(
            instance.old_flavor, instance.image_meta)
        new_vtpm_config = hardware.get_vtpm_constraint(
            instance.new_flavor, instance.image_meta)

        if old_vtpm_config and not new_vtpm_config:
            # the instance no longer cares for its vTPM so delete the related
            # secret; the deletion of the instance directory and undefining of
            # the domain will take care of the TPM files themselves
            LOG.info('New flavor no longer requests vTPM; deleting secret.')
            crypto.delete_vtpm_secret(context, instance)

    # TODO(stephenfin): Fold this back into its only caller, cleanup_resize
    def _cleanup_resize(self, context, instance, network_info):
        inst_base = libvirt_utils.get_instance_path(instance)
        target = inst_base + '_resize'

        # zero the data on backend old pmem device
        vpmems = self._get_vpmems(instance, prefix='old')
        if vpmems:
            self._cleanup_vpmems(vpmems)

        # Remove any old vTPM data, if necessary
        self._cleanup_resize_vtpm(context, instance)

        # Deletion can fail over NFS, so retry the deletion as required.
        # Set maximum attempt as 5, most test can remove the directory
        # for the second time.
        attempts = 0
        while(os.path.exists(target) and attempts < 5):
            shutil.rmtree(target, ignore_errors=True)
            if os.path.exists(target):
                time.sleep(random.randint(20, 200) / 100.0)
            attempts += 1

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
            if root_disk.exists():
                root_disk.remove_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)

        if instance.host != CONF.host:
            self._undefine_domain(instance)
            # TODO(sean-k-mooney): remove this call to unplug_vifs after
            # Wallaby is released. VIFs are now unplugged in resize_instance.
            try:
                self.unplug_vifs(instance, network_info)
            except exception.InternalError as e:
                LOG.debug(e, instance=instance)

    def _get_volume_driver(
        self, connection_info: ty.Dict[str, ty.Any]
    ) -> 'volume.LibvirtBaseVolumeDriver':
        """Fetch the nova.virt.libvirt.volume driver

        Based on the provided connection_info return a nova.virt.libvirt.volume
        driver. This will call out to os-brick to construct an connector and
        check if the connector is valid on the underlying host.

        :param connection_info: The connection_info associated with the volume
        :raises: VolumeDriverNotFound if no driver is found or if the host
            doesn't support the requested driver. This retains legacy behaviour
            when only supported drivers were loaded on startup leading to a
            VolumeDriverNotFound being raised later if an invalid driver was
            requested.
        """
        driver_type = connection_info.get('driver_volume_type')

        # If the driver_type isn't listed in the supported type list fail
        if driver_type not in VOLUME_DRIVERS:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)

        # Return the cached driver
        if driver_type in self.volume_drivers:
            return self.volume_drivers.get(driver_type)

        @utils.synchronized('cache_volume_driver')
        def _cache_volume_driver(driver_type):
            # Check if another request cached the driver while we waited
            if driver_type in self.volume_drivers:
                return self.volume_drivers.get(driver_type)

            try:
                driver_class = importutils.import_class(
                    VOLUME_DRIVERS.get(driver_type))
                self.volume_drivers[driver_type] = driver_class(self._host)
                return self.volume_drivers.get(driver_type)
            except brick_exception.InvalidConnectorProtocol:
                LOG.debug('Unable to load volume driver %s. It is not '
                          'supported on this host.', driver_type)
                # NOTE(lyarwood): This exception is a subclass of
                # VolumeDriverNotFound to ensure no callers have to change
                # their error handling code after the move to on-demand loading
                # of the volume drivers and associated os-brick connectors.
                raise exception.VolumeDriverNotSupported(
                    volume_driver=VOLUME_DRIVERS.get(driver_type))

        # Cache the volume driver if it hasn't already been
        return _cache_volume_driver(driver_type)

    def _connect_volume(self, context, connection_info, instance,
                        encryption=None):
        vol_driver = self._get_volume_driver(connection_info)
        vol_driver.connect_volume(connection_info, instance)
        try:
            self._attach_encryptor(context, connection_info, encryption)
        except Exception:
            # Encryption failed so rollback the volume connection.
            with excutils.save_and_reraise_exception(logger=LOG):
                LOG.exception("Failure attaching encryptor; rolling back "
                              "volume connection", instance=instance)
                vol_driver.disconnect_volume(connection_info, instance)

    def _should_disconnect_target(self, context, instance, multiattach,
                                  vol_driver, volume_id):
        # NOTE(jdg): Multiattach is a special case (not to be confused
        # with shared_targets). With multiattach we may have a single volume
        # attached multiple times to *this* compute node (ie Server-1 and
        # Server-2).  So, if we receive a call to delete the attachment for
        # Server-1 we need to take special care to make sure that the Volume
        # isn't also attached to another Server on this Node.  Otherwise we
        # will indiscriminantly delete the connection for all Server and that's
        # no good.  So check if it's attached multiple times on this node
        # if it is we skip the call to brick to delete the connection.
        if not multiattach:
            return True

        # NOTE(deiter): Volume drivers using _HostMountStateManager are another
        # special case. _HostMountStateManager ensures that the compute node
        # only attempts to mount a single mountpoint in use by multiple
        # attachments once, and that it is not unmounted until it is no longer
        # in use by any attachments. So we can skip the multiattach check for
        # volume drivers that based on LibvirtMountedFileSystemVolumeDriver.
        if isinstance(vol_driver, fs.LibvirtMountedFileSystemVolumeDriver):
            return True

        connection_count = 0
        volume = self._volume_api.get(context, volume_id)
        attachments = volume.get('attachments', {})
        if len(attachments) > 1:
            # First we get a list of all Server UUID's associated with
            # this Host (Compute Node).  We're going to use this to
            # determine if the Volume being detached is also in-use by
            # another Server on this Host, ie just check to see if more
            # than one attachment.server_id for this volume is in our
            # list of Server UUID's for this Host
            servers_this_host = objects.InstanceList.get_uuids_by_host(
                context, instance.host)

            # NOTE(jdg): nova.volume.cinder translates the
            # volume['attachments'] response into a dict which includes
            # the Server UUID as the key, so we're using that
            # here to check against our server_this_host list
            for server_id, data in attachments.items():
                if server_id in servers_this_host:
                    connection_count += 1
        return (False if connection_count > 1 else True)

    def _disconnect_volume(self, context, connection_info, instance,
                           encryption=None, destroy_secrets=True):
        self._detach_encryptor(
            context,
            connection_info,
            encryption=encryption,
            destroy_secrets=destroy_secrets
        )
        vol_driver = self._get_volume_driver(connection_info)
        volume_id = driver_block_device.get_volume_id(connection_info)
        multiattach = connection_info.get('multiattach', False)
        if self._should_disconnect_target(
                context, instance, multiattach, vol_driver, volume_id):
            vol_driver.disconnect_volume(connection_info, instance)
        else:
            LOG.info('Detected multiple connections on this host for '
                     'volume: %(volume)s, skipping target disconnect.',
                     {'volume': volume_id})

    def _extend_volume(self, connection_info, instance, requested_size):
        vol_driver = self._get_volume_driver(connection_info)
        return vol_driver.extend_volume(connection_info, instance,
                                        requested_size)

    def _allow_native_luksv1(self, encryption=None):
        """Check if QEMU's native LUKSv1 decryption should be used.
        """
        # NOTE(lyarwood): Ensure the LUKSv1 provider is used.
        provider = None
        if encryption:
            provider = encryption.get('provider', None)
        if provider in encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP:
            provider = encryptors.LEGACY_PROVIDER_CLASS_TO_FORMAT_MAP[provider]
        return provider == encryptors.LUKS

    def _get_volume_config(self, instance, connection_info, disk_info):
        vol_driver = self._get_volume_driver(connection_info)
        conf = vol_driver.get_config(connection_info, disk_info)

        if self._sev_enabled(instance.flavor, instance.image_meta):
            designer.set_driver_iommu_for_device(conf)

        self._set_cache_mode(conf)
        return conf

    def _get_volume_encryptor(self, connection_info, encryption):
        root_helper = utils.get_root_helper()
        return encryptors.get_volume_encryptor(root_helper=root_helper,
                                               keymgr=key_manager.API(CONF),
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

    def _attach_encryptor(self, context, connection_info, encryption):
        """Attach the frontend encryptor if one is required by the volume.

        The request context is only used when an encryption metadata dict is
        not provided. The encryption metadata dict being populated is then used
        to determine if an attempt to attach the encryptor should be made.

        """
        # NOTE(lyarwood): Skip any attempt to fetch encryption metadata or the
        # actual passphrase from the key manager if a libvirt secert already
        # exists locally for the volume. This suggests that the instance was
        # only powered off or the underlying host rebooted.
        volume_id = driver_block_device.get_volume_id(connection_info)
        if self._host.find_secret('volume', volume_id):
            LOG.debug("A libvirt secret for volume %s has been found on the "
                      "host, skipping any attempt to create another or attach "
                      "an os-brick encryptor.", volume_id)
            return

        if encryption is None:
            encryption = self._get_volume_encryption(context, connection_info)

        if encryption and self._allow_native_luksv1(encryption=encryption):
            # NOTE(lyarwood): Fetch the associated key for the volume and
            # decode the passphrase from the key.
            # FIXME(lyarwood): c-vol currently creates symmetric keys for use
            # with volumes, leading to the binary to hex to string conversion
            # below.
            keymgr = key_manager.API(CONF)
            key = keymgr.get(context, encryption['encryption_key_id'])
            key_encoded = key.get_encoded()
            passphrase = binascii.hexlify(key_encoded).decode('utf-8')

            # NOTE(lyarwood): Retain the behaviour of the original os-brick
            # encryptors and format any volume that does not identify as
            # encrypted with LUKS.
            # FIXME(lyarwood): Remove this once c-vol correctly formats
            # encrypted volumes during their initial creation:
            # https://bugs.launchpad.net/cinder/+bug/1739442
            device_path = connection_info.get('data').get('device_path')
            if device_path:
                root_helper = utils.get_root_helper()
                if not luks_encryptor.is_luks(root_helper, device_path):
                    encryptor = self._get_volume_encryptor(connection_info,
                                                           encryption)
                    encryptor._format_volume(passphrase, **encryption)

            # NOTE(lyarwood): Store the passphrase as a libvirt secret locally
            # on the compute node. This secret is used later when generating
            # the volume config.
            self._host.create_secret('volume', volume_id, password=passphrase)
        elif encryption:
            encryptor = self._get_volume_encryptor(connection_info,
                                                   encryption)
            encryptor.attach_volume(context, **encryption)

    def _detach_encryptor(self, context, connection_info, encryption,
                          destroy_secrets=True):
        """Detach the frontend encryptor if one is required by the volume.

        The request context is only used when an encryption metadata dict is
        not provided. The encryption metadata dict being populated is then used
        to determine if an attempt to detach the encryptor should be made.

        If native LUKS decryption is enabled then delete previously created
        Libvirt volume secret from the host.
        """
        volume_id = driver_block_device.get_volume_id(connection_info)
        if volume_id and self._host.find_secret('volume', volume_id):
            if not destroy_secrets:
                LOG.debug("Skipping volume secret destruction")
                return
            return self._host.delete_secret('volume', volume_id)

        if encryption is None:
            encryption = self._get_volume_encryption(context, connection_info)

        # NOTE(lyarwood): Handle bugs #1821696 and #1917619 by avoiding the use
        # of the os-brick encryptors if we don't have a device_path. The lack
        # of a device_path here suggests the volume was natively attached to
        # QEMU anyway as volumes without a device_path are not supported by
        # os-brick encryptors. For volumes with a device_path the calls to
        # the os-brick encryptors are safe as they are actually idempotent,
        # ignoring any failures caused by the volumes actually being natively
        # attached previously.
        if (encryption and connection_info['data'].get('device_path') is None):
            return

        if encryption:
            encryptor = self._get_volume_encryptor(connection_info,
                                                   encryption)
            encryptor.detach_volume(**encryption)

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

        # Note(cfb): If the volume has a custom block size, check that that we
        # are using QEMU/KVM. The presence of a block size is considered
        # mandatory by cinder so we fail if we can't honor the request.
        data = {}
        if ('data' in connection_info):
            data = connection_info['data']
        if ('logical_block_size' in data or 'physical_block_size' in data):
            if CONF.libvirt.virt_type not in ["kvm", "qemu"]:
                msg = _("Volume sets block size, but the current "
                        "libvirt hypervisor '%s' does not support custom "
                        "block size") % CONF.libvirt.virt_type
                raise exception.InvalidHypervisorType(msg)

        self._connect_volume(context, connection_info, instance,
                             encryption=encryption)
        disk_info = blockinfo.get_info_from_bdm(
            instance, CONF.libvirt.virt_type, instance.image_meta, bdm)
        if disk_info['bus'] == 'scsi':
            disk_info['unit'] = self._get_scsi_controller_next_unit(guest)

        conf = self._get_volume_config(instance, connection_info, disk_info)

        self._check_discard_for_attach_volume(conf, instance)

        try:
            state = guest.get_power_state(self._host)
            live = state in (power_state.RUNNING, power_state.PAUSED)

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
            LOG.exception('Failed to attach volume at mountpoint: %s',
                          mountpoint, instance=instance)
            with excutils.save_and_reraise_exception():
                self._disconnect_volume(context, connection_info, instance,
                                        encryption=encryption)

    def _swap_volume(self, guest, disk_dev, conf, resize_to, hw_firmware_type):
        """Swap existing disk with a new block device.

        Call virDomainBlockRebase or virDomainBlockCopy with Libvirt >= 6.0.0
        to copy and then pivot to a new volume.

        :param: guest: Guest object representing the guest domain
        :param: disk_dev: Device within the domain that is being swapped
        :param: conf: LibvirtConfigGuestDisk object representing the new volume
        :param: resize_to: Size of the dst volume, 0 if the same as the src
        :param: hw_firmware_type: fields.FirmwareType if set in the imagemeta
        """
        dev = guest.get_block_device(disk_dev)

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
            # NOTE (rmk): virDomainBlockRebase and virDomainBlockCopy cannot be
            # executed on persistent domains, so we need to temporarily
            # undefine it. If any part of this block fails, the domain is
            # re-defined regardless.
            if guest.has_persistent_configuration():
                support_uefi = self._check_uefi_support(hw_firmware_type)
                guest.delete_configuration(support_uefi)

            try:
                dev.copy(conf.to_xml(), reuse_ext=True)

                while not dev.is_job_complete():
                    time.sleep(0.5)

                dev.abort_job(pivot=True)

            except Exception as exc:
                # NOTE(lyarwood): conf.source_path is not set for RBD disks so
                # fallback to conf.target_dev when None.
                new_path = conf.source_path or conf.target_dev
                old_path = disk_dev
                LOG.exception("Failure rebasing volume %(new_path)s on "
                    "%(old_path)s.", {'new_path': new_path,
                                      'old_path': old_path})
                raise exception.VolumeRebaseFailed(reason=str(exc))

            if resize_to:
                dev.resize(resize_to * units.Gi)

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

        # NOTE(lyarwood): https://bugzilla.redhat.com/show_bug.cgi?id=760547
        old_encrypt = self._get_volume_encryption(context, old_connection_info)
        new_encrypt = self._get_volume_encryption(context, new_connection_info)
        if ((old_encrypt and self._allow_native_luksv1(old_encrypt)) or
            (new_encrypt and self._allow_native_luksv1(new_encrypt))):
            raise NotImplementedError(_("Swap volume is not supported for "
                "encrypted volumes when native LUKS decryption is enabled."))

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
        self._connect_volume(context, new_connection_info, instance)
        conf = self._get_volume_config(
            instance, new_connection_info, disk_info)
        hw_firmware_type = instance.image_meta.properties.get(
            'hw_firmware_type')

        try:
            self._swap_volume(guest, disk_dev, conf,
                              resize_to, hw_firmware_type)
        except exception.VolumeRebaseFailed:
            with excutils.save_and_reraise_exception():
                self._disconnect_volume(context, new_connection_info, instance)

        self._disconnect_volume(context, old_connection_info, instance)

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

    def emit_event(self, event: virtevent.InstanceEvent) -> None:
        """Handles libvirt specific events locally and dispatches the rest to
        the compute manager.
        """
        if isinstance(event, libvirtevent.LibvirtEvent):
            # These are libvirt specific events handled here on the driver
            # level instead of propagating them to the compute manager level
            if isinstance(event, libvirtevent.DeviceEvent):
                had_clients = self._device_event_handler.notify_waiters(event)

                if had_clients:
                    LOG.debug(
                        "Received event %s from libvirt while the driver is "
                        "waiting for it; dispatched.",
                        event,
                    )
                else:
                    LOG.warning(
                        "Received event %s from libvirt but the driver is not "
                        "waiting for it; ignored.",
                        event,
                    )
            else:
                LOG.debug(
                    "Received event %s from libvirt but no handler is "
                    "implemented for it in the libvirt driver so it is "
                    "ignored", event)
        else:
            # Let the generic driver code dispatch the event to the compute
            # manager
            super().emit_event(event)

    def _detach_with_retry(
        self,
        guest: libvirt_guest.Guest,
        instance_uuid: str,
        # to properly typehint this param we would need typing.Protocol but
        # that is only available since python 3.8
        get_device_conf_func: ty.Callable,
        device_name: str,
    ) -> None:
        """Detaches a device from the guest

        If the guest is a running state then the detach is performed on both
        the persistent and live domains.

        In case of live detach this call will wait for the libvirt event
        signalling the end of the detach process.

        If the live detach times out then it will retry the detach. Detach from
        the persistent config is not retried as it is:

        * synchronous and no event is sent from libvirt
        * it is always expected to succeed if the device is in the domain
          config

        :param guest: the guest we are detach the device from
        :param instance_uuid: the UUID of the instance we are detaching the
            device from
        :param get_device_conf_func: function which returns the configuration
            for device from the domain, having one optional boolean parameter
            `from_persistent_config` to select which domain config to query
        :param device_name: This is the name of the device used solely for
            error messages. Note that it is not the same as the device alias
            used by libvirt to identify the device.
        :raises exception.DeviceNotFound: if the device does not exist in the
            domain even before we try to detach or if libvirt reported that the
            device is missing from the domain synchronously.
        :raises exception.DeviceDetachFailed: if libvirt reported error during
            detaching from the live domain or we timed out waiting for libvirt
            events and run out of retries
        :raises libvirt.libvirtError: for any other errors reported by libvirt
            synchronously.
        """
        state = guest.get_power_state(self._host)
        live = state in (power_state.RUNNING, power_state.PAUSED)

        persistent = guest.has_persistent_configuration()

        if not persistent and not live:
            # nothing to do
            return

        persistent_dev = None
        if persistent:
            persistent_dev = get_device_conf_func(from_persistent_config=True)

        live_dev = None
        if live:
            live_dev = get_device_conf_func()

        # didn't find the device in either domain
        if persistent_dev is None and live_dev is None:
            raise exception.DeviceNotFound(device=device_name)

        if persistent_dev:
            try:
                self._detach_from_persistent(
                    guest, instance_uuid, persistent_dev, get_device_conf_func,
                    device_name)
            except exception.DeviceNotFound:
                if live_dev:
                    # ignore the error so that we can do the live detach
                    LOG.warning(
                        'Libvirt reported sync error while detaching '
                        'device %s from instance %s from the persistent '
                        'domain config. Ignoring the error to proceed with '
                        'live detach as the device exists in the live domain.',
                        device_name, instance_uuid)
                else:
                    # if only persistent detach was requested then give up
                    raise

        if live_dev:
            self._detach_from_live_with_retry(
                guest, instance_uuid, live_dev, get_device_conf_func,
                device_name)

    def _detach_from_persistent(
        self,
        guest: libvirt_guest.Guest,
        instance_uuid: str,
        persistent_dev: ty.Union[
            vconfig.LibvirtConfigGuestDisk,
            vconfig.LibvirtConfigGuestInterface],
        get_device_conf_func,
        device_name: str,
    ):
        LOG.debug(
            'Attempting to detach device %s from instance %s from '
            'the persistent domain config.', device_name, instance_uuid)

        self._detach_sync(
            persistent_dev, guest, instance_uuid, device_name,
            persistent=True, live=False)

        # make sure the dev is really gone
        persistent_dev = get_device_conf_func(
            from_persistent_config=True)
        if not persistent_dev:
            LOG.info(
                'Successfully detached device %s from instance %s '
                'from the persistent domain config.',
                device_name, instance_uuid)
        else:
            # Based on the libvirt devs this should never happen
            LOG.warning(
                'Failed to detach device %s from instance %s '
                'from the persistent domain config. Libvirt did not '
                'report any error but the device is still in the '
                'config.', device_name, instance_uuid)

    def _detach_from_live_with_retry(
        self,
        guest: libvirt_guest.Guest,
        instance_uuid: str,
        live_dev: ty.Union[
            vconfig.LibvirtConfigGuestDisk,
            vconfig.LibvirtConfigGuestInterface],
        get_device_conf_func,
        device_name: str,
    ):
        max_attempts = CONF.libvirt.device_detach_attempts
        for attempt in range(max_attempts):
            LOG.debug(
                '(%s/%s): Attempting to detach device %s with device '
                'alias %s from instance %s from the live domain config.',
                attempt + 1, max_attempts, device_name, live_dev.alias,
                instance_uuid)

            self._detach_from_live_and_wait_for_event(
                live_dev, guest, instance_uuid, device_name)

            # make sure the dev is really gone
            live_dev = get_device_conf_func()
            if not live_dev:
                LOG.info(
                    'Successfully detached device %s from instance %s '
                    'from the live domain config.', device_name, instance_uuid)
                # we are done
                return

            LOG.debug(
                'Failed to detach device %s with device alias %s from '
                'instance %s from the live domain config. Libvirt did not '
                'report any error but the device is still in the config.',
                device_name, live_dev.alias, instance_uuid)

        msg = (
            'Run out of retry while detaching device %s with device '
            'alias %s from instance %s from the live domain config. '
            'Device is still attached to the guest.')
        LOG.error(msg, device_name, live_dev.alias, instance_uuid)
        raise exception.DeviceDetachFailed(
            device=device_name,
            reason=msg % (device_name, live_dev.alias, instance_uuid))

    def _detach_from_live_and_wait_for_event(
        self,
        dev: ty.Union[
            vconfig.LibvirtConfigGuestDisk,
            vconfig.LibvirtConfigGuestInterface],
        guest: libvirt_guest.Guest,
        instance_uuid: str,
        device_name: str,
    ) -> None:
        """Detaches a device from the live config of the guest and waits for
        the libvirt event singling the finish of the detach.

        :param dev: the device configuration to be detached
        :param guest: the guest we are detach the device from
        :param instance_uuid: the UUID of the instance we are detaching the
            device from
        :param device_name: This is the name of the device used solely for
            error messages.
        :raises exception.DeviceNotFound: if libvirt reported that the device
            is missing from the domain synchronously.
        :raises libvirt.libvirtError: for any other errors reported by libvirt
            synchronously.
        :raises DeviceDetachFailed: if libvirt sent DeviceRemovalFailedEvent
        """
        # So we will issue an detach to libvirt and we will wait for an
        # event from libvirt about the result. We need to set up the event
        # handling before the detach to avoid missing the event if libvirt
        # is really fast
        # NOTE(gibi): we need to use the alias name of the device as that
        # is what libvirt will send back to us in the event
        waiter = self._device_event_handler.create_waiter(
            instance_uuid, dev.alias,
            {libvirtevent.DeviceRemovedEvent,
             libvirtevent.DeviceRemovalFailedEvent})
        try:
            self._detach_sync(
                dev, guest, instance_uuid, device_name, persistent=False,
                live=True)
        except Exception:
            # clean up the libvirt event handler as we failed synchronously
            self._device_event_handler.delete_waiter(waiter)
            raise

        LOG.debug(
            'Start waiting for the detach event from libvirt for '
            'device %s with device alias %s for instance %s',
            device_name, dev.alias, instance_uuid)
        # We issued the detach without any exception so we can wait for
        # a libvirt event to arrive to notify us about the result
        # NOTE(gibi): we expect that this call will be unblocked by an
        # incoming libvirt DeviceRemovedEvent or DeviceRemovalFailedEvent
        event = self._device_event_handler.wait(
            waiter, timeout=CONF.libvirt.device_detach_timeout)

        if not event:
            # This should not happen based on information from the libvirt
            # developers. But it does at least during the cleanup of the
            # tempest test case
            # ServerRescueNegativeTestJSON.test_rescued_vm_detach_volume
            # Log a warning and let the upper layer detect that the device is
            # still attached and retry
            LOG.error(
                'Waiting for libvirt event about the detach of '
                'device %s with device alias %s from instance %s is timed '
                'out.', device_name, dev.alias, instance_uuid)

        if isinstance(event, libvirtevent.DeviceRemovalFailedEvent):
            # Based on the libvirt developers this signals a permanent failure
            LOG.error(
                'Received DeviceRemovalFailedEvent from libvirt for the '
                'detach of device %s with device alias %s from instance %s ',
                device_name, dev.alias, instance_uuid)
            raise exception.DeviceDetachFailed(
                device=device_name,
                reason="DeviceRemovalFailedEvent received from libvirt")

    @staticmethod
    def _detach_sync(
        dev: ty.Union[
            vconfig.LibvirtConfigGuestDisk,
            vconfig.LibvirtConfigGuestInterface],
        guest: libvirt_guest.Guest,
        instance_uuid: str,
        device_name: str,
        persistent: bool,
        live: bool,
    ):
        """Detaches a device from the guest without waiting for libvirt events

        It only handles synchronous errors (i.e. exceptions) but does not wait
        for any event from libvirt.

        :param dev: the device configuration to be detached
        :param guest: the guest we are detach the device from
        :param instance_uuid: the UUID of the instance we are detaching the
            device from
        :param device_name: This is the name of the device used solely for
            error messages.
        :param live: detach the device from the live domain config only
        :param persistent: detach the device from the persistent domain config
            only
        :raises exception.DeviceNotFound: if libvirt reported that the device
            is missing from the domain synchronously.
        :raises libvirt.libvirtError: for any other errors reported by libvirt
            synchronously.
        """
        try:
            guest.detach_device(dev, persistent=persistent, live=live)
        except libvirt.libvirtError as ex:
            code = ex.get_error_code()
            msg = ex.get_error_message()
            LOG.debug(
                "Libvirt returned error while detaching device %s from "
                "instance %s. Libvirt error code: %d, error message: %s.",
                device_name, instance_uuid, code, msg
            )
            if (code == libvirt.VIR_ERR_DEVICE_MISSING or
                # Libvirt 4.1 improved error code usage but OPERATION_FAILED
                # still used in one case during detach:
                # https://github.com/libvirt/libvirt/blob/55ea45acc99c549c7757efe954aacc33ad30a8ef/src/qemu/qemu_hotplug.c#L5324-L5328
                # TODO(gibi): remove this when a future version of libvirt
                # transform this error to VIR_ERR_DEVICE_MISSING too.
                (code == libvirt.VIR_ERR_OPERATION_FAILED and
                 'not found' in msg)
            ):
                LOG.debug(
                    'Libvirt failed to detach device %s from instance %s '
                    'synchronously (persistent=%s, live=%s) with error: %s.',
                    device_name, instance_uuid, persistent, live, str(ex))
                raise exception.DeviceNotFound(device=device_name) from ex

            # NOTE(lyarwood): https://bugzilla.redhat.com/1878659
            # Ignore this known QEMU bug for the time being allowing
            # our retry logic to handle it.
            # NOTE(gibi): This can only happen in case of detaching from the
            # live domain as we never retry a detach from the persistent
            # domain so we cannot hit an already running detach there.
            # In case of detaching from the live domain this error can happen
            # if the caller timed out during the first detach attempt then saw
            # that the device is still attached and therefore looped over and
            # and retried the detach. In this case the previous attempt stopped
            # waiting for the libvirt event. Also libvirt reports that there is
            # a detach ongoing, so the current attempt expects that a
            # libvirt event will be still emitted. Therefore we simply return
            # from here. Then the caller will wait for such event.
            if (code == libvirt.VIR_ERR_INTERNAL_ERROR and msg and
                    'already in the process of unplug' in msg
            ):
                LOG.debug(
                    'Ignoring QEMU rejecting our request to detach device %s '
                    'from instance %s as it is caused by a previous request '
                    'still being in progress.', device_name, instance_uuid)
                return

            if code == libvirt.VIR_ERR_NO_DOMAIN:
                LOG.warning(
                    "During device detach, instance disappeared.",
                    instance_uuid=instance_uuid)
                # if the domain has disappeared then we have nothing to detach
                return

            LOG.warning(
                'Unexpected libvirt error while detaching device %s from '
                'instance %s: %s', device_name, instance_uuid, str(ex))
            raise

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        disk_dev = mountpoint.rpartition("/")[2]
        try:
            guest = self._host.get_guest(instance)

            # NOTE(lyarwood): The volume must be detached from the VM before
            # detaching any attached encryptors or disconnecting the underlying
            # volume in _disconnect_volume. Otherwise, the encryptor or volume
            # driver may report that the volume is still in use.
            get_dev = functools.partial(guest.get_disk, disk_dev)
            self._detach_with_retry(
                guest,
                instance.uuid,
                get_dev,
                device_name=disk_dev,
            )
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

        self._disconnect_volume(context, connection_info, instance,
                                encryption=encryption)

    def _resize_attached_volume(self, new_size, block_device, instance):
        LOG.debug('Resizing target device %(dev)s to %(size)u',
                  {'dev': block_device._disk, 'size': new_size},
                  instance=instance)
        block_device.resize(new_size)

    def _resize_attached_encrypted_volume(self, original_new_size,
                                          block_device, instance,
                                          connection_info, encryption):
        # TODO(lyarwood): Also handle the dm-crpyt encryption providers of
        # plain and LUKSv2, for now just use the original_new_size.
        decrypted_device_new_size = original_new_size

        # NOTE(lyarwood): original_new_size currently refers to the total size
        # of the extended volume in bytes. With natively decrypted LUKSv1
        # volumes we need to ensure this now takes the LUKSv1 header and key
        # material into account. Otherwise QEMU will attempt and fail to grow
        # host block devices and remote RBD volumes.
        if self._allow_native_luksv1(encryption):
            try:
                # NOTE(lyarwood): Find the path to provide to qemu-img
                if 'device_path' in connection_info['data']:
                    path = connection_info['data']['device_path']
                elif connection_info['driver_volume_type'] == 'rbd':
                    volume_name = connection_info['data']['name']
                    path = f"rbd:{volume_name}"
                    if connection_info['data'].get('auth_enabled'):
                        username = connection_info['data']['auth_username']
                        path = f"rbd:{volume_name}:id={username}"
                else:
                    path = 'unknown'
                    raise exception.DiskNotFound(location='unknown')

                info = images.privileged_qemu_img_info(path)
                format_specific_data = info.format_specific['data']
                payload_offset = format_specific_data['payload-offset']

                # NOTE(lyarwood): Ensure the underlying device is not resized
                # by subtracting the LUKSv1 payload_offset (where the users
                # encrypted data starts) from the original_new_size (the total
                # size of the underlying volume). Both are reported in bytes.
                decrypted_device_new_size = original_new_size - payload_offset

            except exception.DiskNotFound:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Unable to access the encrypted disk %s.',
                                  path, instance=instance)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.exception('Unknown error when attempting to find the '
                                  'payload_offset for LUKSv1 encrypted disk '
                                  '%s.', path, instance=instance)
        # NOTE(lyarwood): Resize the decrypted device within the instance to
        # the calculated size as with normal volumes.
        self._resize_attached_volume(
            decrypted_device_new_size, block_device, instance)

    def extend_volume(self, context, connection_info, instance,
                      requested_size):
        volume_id = driver_block_device.get_volume_id(connection_info)
        try:
            new_size = self._extend_volume(
                connection_info, instance, requested_size)

            # NOTE(lyarwood): Handle cases where os-brick has ignored failures
            # and returned an invalid new_size of None through the vol drivers
            if new_size is None:
                raise exception.VolumeExtendFailed(
                    volume_id=volume_id,
                    reason="Failure to resize underlying volume on compute."
                )

        except NotImplementedError:
            raise exception.ExtendVolumeNotSupported()

        # Resize the device in QEMU so its size is updated and
        # detected by the instance without rebooting.
        try:
            guest = self._host.get_guest(instance)
            state = guest.get_power_state(self._host)
            active_state = state in (power_state.RUNNING, power_state.PAUSED)
            if active_state:
                if 'device_path' in connection_info['data']:
                    disk_path = connection_info['data']['device_path']
                else:
                    # Some drivers (eg. net) don't put the device_path
                    # into the connection_info. Match disks by their serial
                    # number instead
                    disk = next(iter([
                        d for d in guest.get_all_disks()
                        if d.serial == volume_id
                    ]), None)
                    if not disk:
                        raise exception.VolumeNotFound(volume_id=volume_id)
                    disk_path = disk.target_dev
                dev = guest.get_block_device(disk_path)
                encryption = encryptors.get_encryption_metadata(
                    context, self._volume_api, volume_id, connection_info)
                if encryption:
                    self._resize_attached_encrypted_volume(
                        new_size, dev, instance,
                        connection_info, encryption)
                else:
                    self._resize_attached_volume(
                        new_size, dev, instance)
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
        cfg = self.vif_driver.get_config(instance, vif, image_meta,
                                         instance.flavor,
                                         CONF.libvirt.virt_type)

        if self._sev_enabled(instance.flavor, image_meta):
            designer.set_driver_iommu_for_device(cfg)

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
        try:
            guest.set_metadata(
                self._get_guest_config_meta(
                    instance, instance.get_network_info()))
        except libvirt.libvirtError:
            LOG.warning('updating libvirt metadata failed.', instance=instance)

    def detach_interface(self, context, instance, vif):
        guest = self._host.get_guest(instance)
        cfg = self.vif_driver.get_config(instance, vif,
                                         instance.image_meta,
                                         instance.flavor,
                                         CONF.libvirt.virt_type)
        try:
            get_dev = functools.partial(guest.get_interface_by_cfg, cfg)
            self._detach_with_retry(
                guest,
                instance.uuid,
                get_dev,
                device_name=self.vif_driver.get_vif_devname(vif),
            )
        except exception.DeviceNotFound:
            # The interface is gone so just log it as a warning.
            LOG.warning('Detaching interface %(mac)s failed because '
                        'the device is no longer found on the guest.',
                        {'mac': vif.get('address')}, instance=instance)
        finally:
            # NOTE(gibi): we need to unplug the vif _after_ the detach is done
            # on the libvirt side as otherwise libvirt will still manage the
            # device that our unplug code trying to reset. This can cause a
            # race and leave the detached device configured. Also even if we
            # are failed to detach due to race conditions the unplug is
            # necessary for the same reason
            self.vif_driver.unplug(instance, vif)
        try:
            # NOTE(nmiki): In order for the interface to be removed from
            # network_info, the nova-compute process need to wait for
            # processing on the neutron side.
            # Here, I simply exclude the target VIF from metadata.
            network_info = list(filter(lambda info: info['id'] != vif['id'],
                                       instance.get_network_info()))
            guest.set_metadata(
                self._get_guest_config_meta(instance, network_info))
        except libvirt.libvirtError:
            LOG.warning('updating libvirt metadata failed.', instance=instance)

    def _create_snapshot_metadata(self, image_meta, instance,
                                  img_fmt, snp_name):
        metadata = {'status': 'active',
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

        snapshot_name = uuidutils.generate_uuid(dashed=False)

        # store current state so we know what to resume back to if we suspend
        original_power_state = guest.get_power_state(self._host)

        # NOTE(dgenin): Instances with LVM encrypted ephemeral storage require
        #               cold snapshots. Currently, checking for encryption is
        #               redundant because LVM supports only cold snapshots.
        #               It is necessary in case this situation changes in the
        #               future.
        if (
            self._host.has_min_version(hv_type=host.HV_DRIVER_QEMU) and
            source_type != 'lvm' and
            not CONF.ephemeral_storage_encryption.enabled and
            not CONF.workarounds.disable_libvirt_livesnapshot and
            # NOTE(stephenfin): Live snapshotting doesn't make sense for
            # shutdown instances
            original_power_state != power_state.SHUTDOWN
        ):
            live_snapshot = True
        else:
            live_snapshot = False

        self._suspend_guest_for_snapshot(
            context, live_snapshot, original_power_state, instance)

        root_disk = self.image_backend.by_libvirt_path(
            instance, disk_path, image_type=source_type)

        if live_snapshot:
            LOG.info("Beginning live snapshot process", instance=instance)
        else:
            LOG.info("Beginning cold snapshot process", instance=instance)

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)

        try:
            metadata['location'] = root_disk.direct_snapshot(
                context, snapshot_name, image_format, image_id,
                instance.image_ref)
            self._resume_guest_after_snapshot(
                context, live_snapshot, original_power_state, instance, guest)
            self._image_api.update(context, image_id, metadata,
                                   purge_props=False)
        except (NotImplementedError, exception.ImageUnacceptable,
                exception.Forbidden) as e:
            if type(e) != NotImplementedError:
                LOG.warning('Performing standard snapshot because direct '
                            'snapshot failed: %(error)s',
                            {'error': encodeutils.exception_to_unicode(e)})
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
                self._suspend_guest_for_snapshot(
                    context, live_snapshot, original_power_state, instance)

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
                    LOG.info("Snapshot extracted, beginning image upload",
                             instance=instance)
                except libvirt.libvirtError as ex:
                    error_code = ex.get_error_code()
                    if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                        LOG.info('Instance %(instance_name)s disappeared '
                                 'while taking snapshot of it: [Error Code '
                                 '%(error_code)s] %(ex)s',
                                 {'instance_name': instance.name,
                                  'error_code': error_code,
                                  'ex': ex},
                                 instance=instance)
                        raise exception.InstanceNotFound(
                            instance_id=instance.uuid)
                    else:
                        raise
                finally:
                    self._resume_guest_after_snapshot(
                        context, live_snapshot, original_power_state, instance,
                        guest)

                # Upload that image to the image service
                update_task_state(task_state=task_states.IMAGE_UPLOADING,
                        expected_state=task_states.IMAGE_PENDING_UPLOAD)
                with libvirt_utils.file_open(out_path, 'rb') as image_file:
                    # execute operation with disk concurrency semaphore
                    with compute_utils.disk_ops_semaphore:
                        self._image_api.update(context,
                                               image_id,
                                               metadata,
                                               image_file)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception("Failed to snapshot image")
                failed_snap = metadata.pop('location', None)
                if failed_snap:
                    failed_snap = {'url': str(failed_snap)}
                root_disk.cleanup_direct_snapshot(
                        failed_snap, also_destroy_volume=True,
                        ignore_errors=True)

        LOG.info("Snapshot image upload complete", instance=instance)

    def _needs_suspend_resume_for_snapshot(
        self,
        live_snapshot: bool,
        current_power_state: int,
    ):
        # NOTE(dkang): managedSave does not work for LXC
        if CONF.libvirt.virt_type == 'lxc':
            return False

        # Live snapshots do not necessitate suspending the domain
        if live_snapshot:
            return False

        # ...and neither does a non-running domain
        return current_power_state in (power_state.RUNNING, power_state.PAUSED)

    def _suspend_guest_for_snapshot(
        self,
        context: nova_context.RequestContext,
        live_snapshot: bool,
        current_power_state: int,
        instance: 'objects.Instance',
    ):
        if self._needs_suspend_resume_for_snapshot(
            live_snapshot, current_power_state,
        ):
            self.suspend(context, instance)

    def _resume_guest_after_snapshot(
        self,
        context: nova_context.RequestContext,
        live_snapshot: bool,
        original_power_state: int,
        instance: 'objects.Instance',
        guest: libvirt_guest.Guest,
    ):
        if not self._needs_suspend_resume_for_snapshot(
            live_snapshot, original_power_state,
        ):
            return

        current_power_state = guest.get_power_state(self._host)

        # TODO(stephenfin): Any reason we couldn't use 'self.resume' here?
        guest.launch(pause=current_power_state == power_state.PAUSED)

        self._attach_pci_devices(
            guest, pci_manager.get_instance_pci_devs(instance))
        self._attach_direct_passthrough_ports(context, instance, guest)

    def _can_set_admin_password(self, image_meta):

        if CONF.libvirt.virt_type in ('kvm', 'qemu'):
            if not image_meta.properties.get('hw_qemu_guest_agent', False):
                raise exception.QemuGuestAgentNotEnabled()
        elif not CONF.libvirt.virt_type == 'parallels':
            raise exception.SetAdminPasswdNotSupported()

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
            if error_code == libvirt.VIR_ERR_AGENT_UNRESPONSIVE:
                LOG.debug('Failed to set password: QEMU agent unresponsive',
                          instance_uuid=instance.uuid)
                raise NotImplementedError()

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
                hw_firmware_type = image_meta.properties.get(
                    'hw_firmware_type')
                support_uefi = self._check_uefi_support(hw_firmware_type)
                guest.delete_configuration(support_uefi)

            # NOTE (rmk): Establish a temporary mirror of our root disk and
            #             issue an abort once we have a complete copy.
            dev.rebase(disk_delta, copy=True, reuse_ext=True, shallow=True)

            while not dev.is_job_complete():
                time.sleep(0.5)

            dev.abort_job()
            nova.privsep.path.chown(disk_delta, uid=os.getuid())
        finally:
            self._host.write_instance_config(xml)
            if quiesced:
                self._set_quiesced(context, instance, image_meta, False)

        # Convert the delta (CoW) image with a backing file to a flat
        # image with no backing file.
        libvirt_utils.extract_snapshot(disk_delta, 'qcow2',
                                       out_path, image_format)

        # Remove the disk_delta file once the snapshot extracted, so that
        # it doesn't hang around till the snapshot gets uploaded
        fileutils.delete_if_exists(disk_delta)

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
            LOG.exception('Failed to send updated snapshot status '
                          'to volume service.')

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
                LOG.exception('Unable to create quiesced VM snapshot, '
                              'attempting again with quiescing disabled.',
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
            LOG.exception('Unable to create VM snapshot, '
                          'failing volume_snapshot operation.',
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
                LOG.exception('Error occurred during volume_snapshot_create, '
                              'sending error status to Cinder.',
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
    def _rebase_with_qemu_img(source_path, rebase_base):
        """Rebase a disk using qemu-img.

        :param source_path: the disk source path to rebase
        :type source_path: string
        :param rebase_base: the new parent in the backing chain
        :type rebase_base: None or string
        """

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
            if os.path.isabs(rebase_base):
                backing_file = rebase_base
            else:
                # this is a probably a volume snapshot case where the
                # rebase_base is relative. See bug
                # https://bugs.launchpad.net/nova/+bug/1885528
                backing_file_name = os.path.basename(rebase_base)
                volume_path = os.path.dirname(source_path)
                backing_file = os.path.join(volume_path, backing_file_name)

            b_file_fmt = images.qemu_img_info(backing_file).file_format
            qemu_img_extra_arg = ['-F', b_file_fmt]

        qemu_img_extra_arg.append(source_path)
        # execute operation with disk concurrency semaphore
        with compute_utils.disk_ops_semaphore:
            processutils.execute("qemu-img", "rebase", "-b", backing_file,
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
        xml = guest.get_xml_desc()
        xml_doc = etree.fromstring(xml)

        device_info = vconfig.LibvirtConfigGuest()
        device_info.parse_dom(xml_doc)

        for guest_disk in device_info.devices:
            if (guest_disk.root_name != 'disk'):
                continue

            if (guest_disk.target_dev is None or guest_disk.serial is None):
                continue

            if (
                guest_disk.source_path is None and
                guest_disk.source_protocol is None
            ):
                continue

            if guest_disk.serial == volume_id:
                my_dev = guest_disk.target_dev

                active_protocol = guest_disk.source_protocol
                active_disk_object = guest_disk
                break
        else:
            LOG.debug('Domain XML: %s', xml, instance=instance)
            msg = (_("Disk with id '%s' not found attached to instance.")
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

            relative = rebase_base is not None
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

                # It's unsure how well qemu-img handles network disks for
                # every protocol. So let's be safe.
                active_protocol = active_disk_object.source_protocol
                if active_protocol is not None:
                    msg = _("Something went wrong when deleting a volume "
                            "snapshot: rebasing a %(protocol)s network disk "
                            "using qemu-img has not been fully tested"
                           ) % {'protocol': active_protocol}
                    LOG.error(msg)
                    raise exception.InternalError(msg)
                self._rebase_with_qemu_img(active_disk_object.source_path,
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
                LOG.exception('Error occurred during volume_snapshot_delete, '
                              'sending error status to Cinder.',
                              instance=instance)
                self._volume_snapshot_update_status(
                    context, snapshot_id, 'error_deleting')

        self._volume_snapshot_update_status(context, snapshot_id, 'deleting')
        self._volume_refresh_connection_info(context, instance, volume_id)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):
        """Reboot a virtual machine, given an instance reference."""
        if reboot_type == 'SOFT':
            # NOTE(vish): This will attempt to do a graceful shutdown/restart.
            try:
                soft_reboot_success = self._soft_reboot(instance)
            except libvirt.libvirtError as e:
                LOG.debug("Instance soft reboot failed: %s",
                          encodeutils.exception_to_unicode(e),
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
                                 block_device_info, accel_info)

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
        for x in range(CONF.libvirt.wait_soft_reboot_seconds):
            guest = self._host.get_guest(instance)

            state = guest.get_power_state(self._host)
            new_domid = guest.id

            # NOTE(ivoks): By checking domain IDs, we make sure we are
            #              not recreating domain that's already running.
            if old_domid != new_domid:
                if state in (power_state.SHUTDOWN, power_state.CRASHED):
                    LOG.info("Instance shutdown successfully.",
                             instance=instance)
                    guest.launch()
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
                     block_device_info=None, accel_info=None):
        """Reboot a virtual machine, given an instance reference.

        Performs a Libvirt reset (if supported) on the domain.

        If Libvirt reset is unavailable this method actually destroys and
        re-creates the domain to ensure the reboot happens, as the guest
        OS cannot ignore this action.
        """
        # NOTE(sbauza): Since we undefine the guest XML when destroying, we
        # need to remember the existing mdevs for reusing them.
        mdevs = self._get_all_assigned_mediated_devices(instance)
        mdevs = list(mdevs.keys())
        # NOTE(mdbooth): In addition to performing a hard reboot of the domain,
        # the hard reboot operation is relied upon by operators to be an
        # automated attempt to fix as many things as possible about a
        # non-functioning instance before resorting to manual intervention.
        # With this goal in mind, we tear down all the aspects of an instance
        # we can here without losing data. This allows us to re-initialise from
        # scratch, and hopefully fix, most aspects of a non-functioning guest.
        self.destroy(context, instance, network_info, destroy_disks=False,
                     block_device_info=block_device_info,
                     destroy_secrets=False)

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
                                  block_device_info=block_device_info,
                                  mdevs=mdevs, accel_info=accel_info)

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
        external_events = []
        vifs_already_plugged = True
        event_expected_for_vnic_types = (
            CONF.workarounds.wait_for_vif_plugged_event_during_hard_reboot)
        if event_expected_for_vnic_types:
            # NOTE(gibi): We unplugged every vif during destroy above and we
            # will replug them with _create_guest_with_network. As the
            # workaround config has some vnic_types configured we expect
            # vif-plugged events for every vif with those vnic_types.
            # TODO(gibi): only wait for events if we know that the networking
            # backend sends plug time events. For that we need to finish
            # https://bugs.launchpad.net/neutron/+bug/1821058 first in Neutron
            # then create a driver -> plug-time event mapping in nova.
            external_events = [
                ('network-vif-plugged', vif['id'])
                for vif in network_info
                if vif['vnic_type'] in event_expected_for_vnic_types
            ]
            vifs_already_plugged = False

        # NOTE(efried): The instance should already have a vtpm_secret_uuid
        # registered if appropriate.
        self._create_guest_with_network(
            context, xml, instance, network_info, block_device_info,
            vifs_already_plugged=vifs_already_plugged,
            external_events=external_events)

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
                 block_device_info=None, accel_info=None):
        """Power on the specified instance."""
        # We use _hard_reboot here to ensure that all backing files,
        # network, and block device connections, etc. are established
        # and available before we attempt to start the instance.
        self._hard_reboot(context, instance, network_info, block_device_info,
                          accel_info)

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

            LOG.exception(
                'Error from libvirt while injecting an NMI to '
                '%(instance_uuid)s: [Error Code %(error_code)s] %(ex)s',
                {'instance_uuid': instance.uuid,
                 'error_code': error_code, 'ex': ex})
            raise

    def suspend(self, context, instance):
        """Suspend the specified instance."""
        guest = self._host.get_guest(instance)

        self._detach_pci_devices(guest,
            pci_manager.get_instance_pci_devs(instance))
        self._detach_direct_passthrough_ports(context, instance, guest)
        self._detach_mediated_devices(guest)
        guest.save_memory_state()

    def resume(self, context, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        xml = self._get_existing_domain_xml(instance, network_info,
                                            block_device_info)
        # NOTE(gsantos): The mediated devices that were removed on suspension
        # are still present in the xml. Let's take their references from it
        # and re-attach them.
        mdevs = self._get_mdevs_from_guest_config(xml)
        # NOTE(efried): The instance should already have a vtpm_secret_uuid
        # registered if appropriate.
        guest = self._create_guest_with_network(
            context, xml, instance, network_info, block_device_info,
            vifs_already_plugged=True)
        self._attach_pci_devices(guest,
            pci_manager.get_instance_pci_devs(instance))
        self._attach_direct_passthrough_ports(
            context, instance, guest, network_info)
        self._attach_mediated_devices(guest, mdevs)
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
               rescue_password, block_device_info):
        """Loads a VM using rescue images.

        A rescue is normally performed when something goes wrong with the
        primary images and data needs to be corrected/recovered. Rescuing
        should not edit or over-ride the original image, only allow for
        data recovery.

        Two modes are provided when rescuing an instance with this driver.

        The original and default rescue mode, where the rescue boot disk,
        original root disk and optional regenerated config drive are attached
        to the instance.

        A second stable device rescue mode is also provided where all of the
        original devices are attached to the instance during the rescue attempt
        with the addition of the rescue boot disk. This second mode is
        controlled by the hw_rescue_device and hw_rescue_bus image properties
        on the rescue image provided to this method via image_meta.

        :param nova.context.RequestContext context:
            The context for the rescue.
        :param nova.objects.instance.Instance instance:
            The instance being rescued.
        :param nova.network.model.NetworkInfo network_info:
            Necessary network information for the resume.
        :param nova.objects.ImageMeta image_meta:
            The metadata of the image of the instance.
        :param rescue_password: new root password to set for rescue.
        :param dict block_device_info:
            The block device mapping of the instance.
        """
        instance_dir = libvirt_utils.get_instance_path(instance)
        unrescue_xml = self._get_existing_domain_xml(instance, network_info)
        unrescue_xml_path = os.path.join(instance_dir, 'unrescue.xml')
        with open(unrescue_xml_path, 'w') as f:
            f.write(unrescue_xml)

        rescue_image_id = None
        rescue_image_meta = None
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

        virt_type = CONF.libvirt.virt_type
        if hardware.check_hw_rescue_props(image_meta):
            LOG.info("Attempting a stable device rescue", instance=instance)
            # NOTE(lyarwood): Stable device rescue is not supported when using
            # the LXC virt_type as it does not support the required
            # <boot order=''> definitions allowing an instance to boot from the
            # rescue device added as a final device to the domain.
            if virt_type == 'lxc':
                reason = _(
                    "Stable device rescue is not supported by virt_type '%s'"
                )
                raise exception.InstanceNotRescuable(
                    instance_id=instance.uuid, reason=reason % virt_type)
            # NOTE(lyarwood): Stable device rescue provides the original disk
            # mapping of the instance with the rescue device appened to the
            # end. As a result we need to provide the original image_meta, the
            # new rescue_image_meta and block_device_info when calling
            # get_disk_info.
            rescue_image_meta = image_meta
            if instance.image_ref:
                image_meta = objects.ImageMeta.from_image_ref(
                    context, self._image_api, instance.image_ref)
            else:
                # NOTE(lyarwood): If instance.image_ref isn't set attempt to
                # lookup the original image_meta from the bdms. This will
                # return an empty dict if no valid image_meta is found.
                image_meta_dict = block_device.get_bdm_image_metadata(
                    context, self._image_api, self._volume_api,
                    block_device_info['block_device_mapping'],
                    legacy_bdm=False)
                image_meta = objects.ImageMeta.from_dict(image_meta_dict)

        else:
            LOG.info("Attempting rescue", instance=instance)
            # NOTE(lyarwood): A legacy rescue only provides the rescue device
            # and the original root device so we don't need to provide
            # block_device_info to the get_disk_info call.
            block_device_info = None

        disk_info = blockinfo.get_disk_info(virt_type, instance, image_meta,
            rescue=True, block_device_info=block_device_info,
            rescue_image_meta=rescue_image_meta)
        LOG.debug("rescue generated disk_info: %s", disk_info)

        injection_info = InjectionInfo(network_info=network_info,
                                       admin_pass=rescue_password,
                                       files=None)
        gen_confdrive = functools.partial(self._create_configdrive,
                                          context, instance, injection_info,
                                          rescue=True)
        # NOTE(sbauza): Since rescue recreates the guest XML, we need to
        # remember the existing mdevs for reusing them.
        mdevs = self._get_all_assigned_mediated_devices(instance)
        mdevs = list(mdevs.keys())
        self._create_image(context, instance, disk_info['mapping'],
                           injection_info=injection_info, suffix='.rescue',
                           disk_images=rescue_images)
        # NOTE(efried): The instance should already have a vtpm_secret_uuid
        # registered if appropriate.
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  image_meta, rescue=rescue_images,
                                  mdevs=mdevs,
                                  block_device_info=block_device_info)
        self._destroy(instance)
        self._create_guest(
            context, xml, instance, post_xml_callback=gen_confdrive,
        )

    def unrescue(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ):
        """Reboot the VM which is being rescued back into primary images."""
        instance_dir = libvirt_utils.get_instance_path(instance)
        unrescue_xml_path = os.path.join(instance_dir, 'unrescue.xml')
        # The xml should already contain the secret_uuid if relevant.
        xml = libvirt_utils.load_file(unrescue_xml_path)

        self._destroy(instance)
        self._create_guest(context, xml, instance)
        os.unlink(unrescue_xml_path)
        rescue_files = os.path.join(instance_dir, "*.rescue")
        for rescue_file in glob.iglob(rescue_files):
            if os.path.isdir(rescue_file):
                shutil.rmtree(rescue_file)
            else:
                os.unlink(rescue_file)
        # cleanup rescue volume
        lvm.remove_volumes([lvmdisk for lvmdisk in self._lvm_disks(instance)
                                if lvmdisk.endswith('.rescue')])
        if CONF.libvirt.images_type == 'rbd':
            filter_fn = lambda disk: (disk.startswith(instance.uuid) and
                                      disk.endswith('.rescue'))
            rbd_utils.RBDDriver().cleanup_volumes(filter_fn)

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):
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
        created_instance_dir, created_disks = self._create_image(
                context, instance, disk_info['mapping'],
                injection_info=injection_info,
                block_device_info=block_device_info)

        # Required by Quobyte CI
        self._ensure_console_log_for_instance(instance)

        # Does the guest need to be assigned some vGPU mediated devices ?
        mdevs = self._allocate_mdevs(allocations)

        # If the guest needs a vTPM, _get_guest_xml needs its secret to exist
        # and its uuid to be registered in the instance prior to _get_guest_xml
        if CONF.libvirt.swtpm_enabled and hardware.get_vtpm_constraint(
            instance.flavor, image_meta
        ):
            if not instance.system_metadata.get('vtpm_secret_uuid'):
                # Create the secret via the key manager service so that we have
                # it to hand when generating the XML. This is slightly wasteful
                # as we'll perform a redundant key manager API call later when
                # we create the domain but the alternative is an ugly mess
                crypto.ensure_vtpm_secret(context, instance)

        xml = self._get_guest_xml(context, instance, network_info,
                                  disk_info, image_meta,
                                  block_device_info=block_device_info,
                                  mdevs=mdevs, accel_info=accel_info)
        self._create_guest_with_network(
            context, xml, instance, network_info, block_device_info,
            post_xml_callback=gen_confdrive,
            power_on=power_on,
            cleanup_instance_dir=created_instance_dir,
            cleanup_instance_disks=created_disks)
        LOG.debug("Guest created on hypervisor", instance=instance)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            state = self.get_info(instance).state

            if state == power_state.RUNNING:
                LOG.info("Instance spawned successfully.", instance=instance)
                raise loopingcall.LoopingCallDone()

        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(_wait_for_boot)
            timer.start(interval=0.5).wait()
        else:
            LOG.info("Instance spawned successfully.", instance=instance)

        # Finally register defaults for any undefined image properties so that
        # future changes by QEMU, libvirt or within this driver don't change
        # the ABI of the instance.
        self._register_undefined_instance_details(context, instance)

    def _get_console_output_file(self, instance, console_log):
        bytes_to_read = MAX_CONSOLE_BYTES
        log_data = b""  # The last N read bytes
        i = 0  # in case there is a log rotation (like "virtlogd")
        path = console_log

        while bytes_to_read > 0 and os.path.exists(path):
            read_log_data, remaining = nova.privsep.path.last_bytes(
                                        path, bytes_to_read)
            # We need the log file content in chronological order,
            # that's why we *prepend* the log data.
            log_data = read_log_data + log_data

            # Prep to read the next file in the chain
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

        # check for different types of consoles
        path_sources = [
            ('file', "./devices/console[@type='file']/source[@path]", 'path'),
            ('tcp', "./devices/console[@type='tcp']/log[@file]", 'file'),
            ('pty', "./devices/console[@type='pty']/source[@path]", 'path')]
        console_type = ""
        console_path = ""
        for c_type, epath, attrib in path_sources:
            node = tree.find(epath)
            if (node is not None) and node.get(attrib):
                console_type = c_type
                console_path = node.get(attrib)
                break

        # instance has no console at all
        if not console_path:
            raise exception.ConsoleNotAvailable()

        # instance has a console, but file doesn't exist (yet?)
        if not os.path.exists(console_path):
            LOG.info('console logfile for instance does not exist',
                      instance=instance)
            return ""

        # pty consoles need special handling
        if console_type == 'pty':
            console_log = self._get_console_log_path(instance)
            data = nova.privsep.libvirt.readpty(console_path)

            # NOTE(markus_z): The virt_types kvm and qemu are the only ones
            # which create a dedicated file device for the console logging.
            # Other virt_types like lxc and parallels depend on the flush of
            # that PTY device into the "console.log" file to ensure that a
            # series of "get_console_output" calls return the complete content
            # even after rebooting a guest.
            nova.privsep.path.writefile(console_log, 'a+', data)

            # set console path to logfile, not to pty device
            console_path = console_log

        # return logfile content
        return self._get_console_output_file(instance, console_path)

    def get_host_ip_addr(self):
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
        host = CONF.vnc.server_proxyclient_address

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
        nova.privsep.fs.unprivileged_mkfs('swap', target)

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
        key = None
        if CONF.libvirt.inject_key and instance.get('key_data'):
            key = str(instance.key_data)

        # Handles the admin password injection.
        admin_pass = None
        if CONF.libvirt.inject_password:
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

        created_instance_dir = True

        # ensure directories exist and are writable
        instance_dir = libvirt_utils.get_instance_path(instance)
        if os.path.exists(instance_dir):
            LOG.debug("Instance directory exists: not creating",
                      instance=instance)
            created_instance_dir = False
        else:
            LOG.debug("Creating instance directory", instance=instance)
            fileutils.ensure_tree(libvirt_utils.get_instance_path(instance))

        LOG.info('Creating image', instance=instance)

        flavor = instance.get_flavor()
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
                swap_mb = flavor['swap']
            else:
                swap = driver.block_device_info_get_swap(block_device_info)
                if driver.swap_is_usable(swap):
                    swap_mb = swap['swap_size']
                elif (flavor['swap'] > 0 and
                      not block_device.volume_in_mapping(
                        mapping['dev'], block_device_info)):
                    swap_mb = flavor['swap']

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

        # NOTE(mdbooth): kernel and ramdisk, if they are defined, are hardcoded
        # to use raw, which means they will always be cleaned up with the
        # instance directory. We must not consider them for created_disks,
        # which may not be using the instance directory.
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

        created_disks = self._create_and_inject_local_root(
            context, instance, booted_from_volume, suffix, disk_images,
            injection_info, fallback_from_host)

        # Lookup the filesystem type if required
        os_type_with_default = nova.privsep.fs.get_fs_type_for_os_type(
            instance.os_type)
        # Generate a file extension based on the file system
        # type and the mkfs commands configured if any
        file_extension = nova.privsep.fs.get_file_extension_for_os_type(
            os_type_with_default, CONF.default_ephemeral_format)

        vm_mode = fields.VMMode.get_from_instance(instance)
        ephemeral_gb = instance.flavor.ephemeral_gb
        if 'disk.local' in disk_mapping:
            disk_image = image('disk.local')
            # Short circuit the exists() tests if we already created a disk
            created_disks = created_disks or not disk_image.exists()

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
            # Short circuit the exists() tests if we already created a disk
            created_disks = created_disks or not disk_image.exists()

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
            swap = image('disk.swap')
            # Short circuit the exists() tests if we already created a disk
            created_disks = created_disks or not swap.exists()
            swap.cache(fetch_func=self._create_swap, context=context,
                       filename="swap_%s" % swap_mb,
                       size=size, swap_mb=swap_mb)

        if created_disks:
            LOG.debug('Created local disks', instance=instance)
        else:
            LOG.debug('Did not create local disks', instance=instance)

        return (created_instance_dir, created_disks)

    def _create_and_inject_local_root(self, context, instance,
                                      booted_from_volume, suffix, disk_images,
                                      injection_info, fallback_from_host):
        created_disks = False

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
            created_disks = not backend.exists()

            if instance.task_state == task_states.RESIZE_FINISH:
                backend.create_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)
            if backend.SUPPORTS_CLONE:
                def clone_fallback_to_fetch(
                    context, target, image_id, trusted_certs=None,
                ):
                    refuse_fetch = (
                        CONF.libvirt.images_type == 'rbd' and
                        CONF.workarounds.never_download_image_if_on_rbd)
                    try:
                        backend.clone(context, disk_images['image_id'])
                    except exception.ImageUnacceptable:
                        if refuse_fetch:
                            # Re-raise the exception from the failed
                            # ceph clone.  The compute manager expects
                            # ImageUnacceptable as a possible result
                            # of spawn(), from which this is called.
                            with excutils.save_and_reraise_exception():
                                LOG.warning(
                                    'Image %s is not on my ceph and '
                                    '[workarounds]/'
                                    'never_download_image_if_on_rbd=True;'
                                    ' refusing to fetch and upload.',
                                    disk_images['image_id'])
                        libvirt_utils.fetch_image(
                            context, target, image_id, trusted_certs,
                        )
                fetch_func = clone_fallback_to_fetch
            else:
                fetch_func = libvirt_utils.fetch_image

            self._try_fetch_image_cache(backend, fetch_func, context,
                                        root_fname, disk_images['image_id'],
                                        instance, size, fallback_from_host)

            # During unshelve or cross cell resize on Qcow2 backend, we spawn()
            # using a snapshot image. Extra work is needed in order to rebase
            # disk image to its original image_ref. Disk backing file will
            # then represent back image_ref instead of snapshot image.
            self._rebase_original_qcow2_image(context, instance, backend)

            if need_inject:
                self._inject_data(backend, instance, injection_info)

        elif need_inject:
            LOG.warning('File injection into a boot from volume '
                        'instance is not supported', instance=instance)

        return created_disks

    def _needs_rebase_original_qcow2_image(self, instance, backend):
        if not isinstance(backend, imagebackend.Qcow2):
            return False
        if instance.vm_state == vm_states.SHELVED_OFFLOADED:
            return True
        if instance.task_state == task_states.RESIZE_FINISH:
            # We need to distinguish between local versus cross cell resize.
            # Rebase is only needed in cross cell case because instance
            # is spawn from a snapshot.
            base_image_ref = instance.system_metadata.get(
                    'image_base_image_ref')
            if base_image_ref != instance.image_ref:
                return True
        return False

    def _rebase_original_qcow2_image(self, context, instance, backend):
        # NOTE(aarents): During qcow2 instance unshelve/cross_cell_resize,
        # backing file represents a snapshot image, not original
        # instance.image_ref. We rebase here instance disk to original image.
        # This second fetch call does nothing except downloading original
        # backing file if missing, as image disk have already been
        # created/resized by first fetch call.

        if not self._needs_rebase_original_qcow2_image(instance, backend):
            return

        base_dir = self.image_cache_manager.cache_dir
        base_image_ref = instance.system_metadata.get('image_base_image_ref')
        root_fname = imagecache.get_cache_fname(base_image_ref)
        base_backing_fname = os.path.join(base_dir, root_fname)

        try:
            self._try_fetch_image_cache(backend, libvirt_utils.fetch_image,
                                        context, root_fname, base_image_ref,
                                        instance, None)
        except exception.ImageNotFound:
            # We must flatten here in order to remove dependency with an orphan
            # backing file (as snapshot image will be dropped once
            # unshelve/cross_cell_resize is successfull).
            LOG.warning('Current disk image is created on top of a snapshot '
                        'image and cannot be rebased to original image '
                        'because it is no longer available in the image '
                        'service, disk will be consequently flattened.',
                        instance=instance)
            base_backing_fname = None

        LOG.info('Rebasing disk image.', instance=instance)
        self._rebase_with_qemu_img(backend.path, base_backing_fname)

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
                    network_info=injection_info.network_info)

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
                                                     CONF.libvirt.virt_type)
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

    def _update_compute_provider_status(self, context, service):
        """Calls the ComputeVirtAPI.update_compute_provider_status method

        :param context: nova auth RequestContext
        :param service: nova.objects.Service record for this host which is
            expected to only manage a single ComputeNode
        """
        rp_uuid = None
        try:
            rp_uuid = service.compute_node.uuid
            self.virtapi.update_compute_provider_status(
                context, rp_uuid, enabled=not service.disabled)
        except Exception:
            # This is best effort so just log the exception but don't fail.
            # The update_available_resource periodic task will sync the trait.
            LOG.warning(
                'An error occurred while updating compute node '
                'resource provider status to "%s" for provider: %s',
                'disabled' if service.disabled else 'enabled',
                rp_uuid or service.host, exc_info=True)

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
                    # Update the disabled trait status on the corresponding
                    # compute node resource provider in placement.
                    self._update_compute_provider_status(ctx, service)
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

    def _get_cpu_model_mapping(self, model):
        """Get the CPU model mapping

        The CPU models which admin configured are case-insensitive, libvirt is
        case-sensitive, therefore build a mapping to get the correct CPU model
        name.

        :param model: Case-insensitive CPU model name.
        :return: It will validate and return the case-sensitive CPU model name
                 if on a supported platform, otherwise it will just return
                 what was provided
        :raises: exception.InvalidCPUInfo if the CPU model is not supported.
        """
        cpu_info = self._get_cpu_info()
        if cpu_info['arch'] not in (fields.Architecture.I686,
                                    fields.Architecture.X86_64,
                                    fields.Architecture.PPC64,
                                    fields.Architecture.PPC64LE,
                                    fields.Architecture.PPC):
            return model

        if not self.cpu_models_mapping:
            cpu_models = self._host.get_cpu_model_names()
            for cpu_model in cpu_models:
                self.cpu_models_mapping[cpu_model.lower()] = cpu_model

        if model.lower() not in self.cpu_models_mapping:
            msg = (_("Configured CPU model: %(model)s is not correct, "
                     "or your host CPU arch does not support this "
                     "model. Please correct your config and try "
                     "again.") % {'model': model})
            raise exception.InvalidCPUInfo(msg)

        return self.cpu_models_mapping.get(model.lower())

    # TODO(stephenfin): Libvirt exposes information about possible CPU models
    # via 'getDomainCapabilities' and we should use it
    def _get_guest_cpu_model_config(self, flavor=None, arch=None):
        mode = CONF.libvirt.cpu_mode
        models = [self._get_cpu_model_mapping(model)
                  for model in CONF.libvirt.cpu_models]
        extra_flags = set([flag.lower() for flag in
            CONF.libvirt.cpu_model_extra_flags])

        if not arch:
            caps = self._host.get_capabilities()
            arch = caps.host.cpu.arch

        if (
            CONF.libvirt.virt_type == "kvm" or
            CONF.libvirt.virt_type == "qemu"
        ):
            if mode is None:
                # AArch64 lacks 'host-model' support because neither libvirt
                # nor QEMU are able to tell what the host CPU model exactly is.
                # And there is no CPU description code for ARM(64) at this
                # point.

                # Also worth noting: 'host-passthrough' mode will completely
                # break live migration, *unless* all the Compute nodes (running
                # libvirtd) have *identical* CPUs.
                if arch == fields.Architecture.AARCH64:
                    mode = "host-passthrough"
                    LOG.info('CPU mode "host-passthrough" was chosen. Live '
                             'migration can break unless all compute nodes '
                             'have identical cpus. AArch64 does not support '
                             'other modes.')
                else:
                    mode = "host-model"
            if mode == "none":
                return vconfig.LibvirtConfigGuestCPU()
            # On AArch64 platform the return of _get_cpu_model_mapping will not
            # return the default CPU model.
            if mode == "custom":
                if arch == fields.Architecture.AARCH64:
                    if not models:
                        models = ['max']

        else:
            if mode is None or mode == "none":
                return None

        cpu = vconfig.LibvirtConfigGuestCPU()
        cpu.mode = mode
        cpu.model = models[0] if models else None

        # compare flavor trait and cpu models, select the first mathched model
        if flavor and mode == "custom":
            flags = libvirt_utils.get_flags_by_flavor_specs(flavor)
            if flags:
                cpu.model = self._match_cpu_model_by_flags(models, flags)

        LOG.debug("CPU mode '%(mode)s' models '%(models)s' was chosen, "
                  "with extra flags: '%(extra_flags)s'",
                  {'mode': mode,
                   'models': (cpu.model or ""),
                   'extra_flags': (extra_flags or "")})

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
        #
        # NOTE(kchamart) Similar to what was done in
        # _check_cpu_compatibility(), the below parses a comma-separated
        # list of CPU flags from `[libvirt]cpu_model_extra_flags` and
        # will selectively enable or disable a given CPU flag for the
        # guest, before it is launched by Nova.
        for flag in extra_flags:
            cpu_feature = self._prepare_cpu_flag(flag)
            cpu.add_feature(cpu_feature)
        return cpu

    def _match_cpu_model_by_flags(self, models, flags):
        for model in models:
            if flags.issubset(self.cpu_model_flag_mapping.get(model, set([]))):
                return model
            cpu = vconfig.LibvirtConfigCPU()
            cpu.arch = self._host.get_capabilities().host.cpu.arch
            cpu.model = model
            features_xml = self._get_guest_baseline_cpu_features(cpu.to_xml())
            if features_xml:
                cpu.parse_str(features_xml)
                feature_names = [f.name for f in cpu.features]
                self.cpu_model_flag_mapping[model] = feature_names
                if flags.issubset(feature_names):
                    return model

        msg = ('No CPU model match traits, models: {models}, required '
               'flags: {flags}'.format(models=models, flags=flags))
        raise exception.InvalidCPUInfo(msg)

    def _get_guest_cpu_config(self, flavor, image_meta,
                              guest_cpu_numa_config, instance_numa_topology):
        arch = libvirt_utils.get_arch(image_meta)
        cpu = self._get_guest_cpu_model_config(flavor, arch)

        if cpu is None:
            return None

        topology = hardware.get_best_cpu_topology(flavor, image_meta)

        cpu.sockets = topology.sockets
        cpu.cores = topology.cores
        cpu.threads = topology.threads
        cpu.numa = guest_cpu_numa_config

        return cpu

    def _get_guest_disk_config(
        self, instance, name, disk_mapping, flavor, image_type=None,
        boot_order=None,
    ):
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
        conf = disk.libvirt_info(
            disk_info, self.disk_cachemode, flavor['extra_specs'],
            disk_unit=disk_unit, boot_order=boot_order)
        return conf

    def _get_guest_fs_config(self, instance, name, image_type=None):
        disk = self.image_backend.by_name(instance, name, image_type)
        return disk.libvirt_fs_info("/", "ploop")

    def _get_guest_storage_config(
        self, context, instance, image_meta, disk_info, rescue,
        block_device_info, flavor, os_type,
    ):
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
                    disk_mapping, flavor)
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

            if rescue and disk_mapping['disk.rescue'] == disk_mapping['root']:
                diskrescue = self._get_guest_disk_config(
                    instance, 'disk.rescue', disk_mapping, flavor)
                devices.append(diskrescue)

                diskos = self._get_guest_disk_config(
                    instance, 'disk', disk_mapping, flavor)
                devices.append(diskos)
            else:
                if 'disk' in disk_mapping:
                    diskos = self._get_guest_disk_config(
                        instance, 'disk', disk_mapping, flavor)
                    devices.append(diskos)

                if 'disk.local' in disk_mapping:
                    disklocal = self._get_guest_disk_config(
                        instance, 'disk.local', disk_mapping, flavor)
                    devices.append(disklocal)
                    instance.default_ephemeral_device = (
                        block_device.prepend_dev(disklocal.target_dev))

                devices = devices + _get_ephemeral_devices()

                if 'disk.swap' in disk_mapping:
                    diskswap = self._get_guest_disk_config(
                        instance, 'disk.swap', disk_mapping, flavor)
                    devices.append(diskswap)
                    instance.default_swap_device = (
                        block_device.prepend_dev(diskswap.target_dev))

            config_name = 'disk.config'
            if rescue and disk_mapping['disk.rescue'] == disk_mapping['root']:
                config_name = 'disk.config.rescue'

            if config_name in disk_mapping:
                diskconfig = self._get_guest_disk_config(
                    instance, config_name, disk_mapping, flavor,
                    self._get_disk_config_image_type())
                devices.append(diskconfig)

        for vol in block_device.get_bdms_to_connect(block_device_mapping,
                                                   mount_rootfs):
            connection_info = vol['connection_info']
            vol_dev = block_device.prepend_dev(vol['mount_device'])
            info = disk_mapping[vol_dev]
            self._connect_volume(context, connection_info, instance)
            if scsi_controller and scsi_controller.model == 'virtio-scsi':
                # Check if this is the bootable volume when in a
                # boot-from-volume instance, and if so, ensure the unit
                # attribute is 0.
                if vol.get('boot_index') == 0:
                    info['unit'] = 0
                else:
                    info['unit'] = disk_mapping['unit']
                    disk_mapping['unit'] += 1
            cfg = self._get_volume_config(instance, connection_info, info)
            devices.append(cfg)
            vol['connection_info'] = connection_info
            vol.save()

        for d in devices:
            self._set_cache_mode(d)

        if scsi_controller:
            devices.append(scsi_controller)

        if rescue and disk_mapping['disk.rescue'] != disk_mapping['root']:
            diskrescue = self._get_guest_disk_config(
                instance, 'disk.rescue', disk_mapping, flavor, boot_order='1')
            devices.append(diskrescue)

        return devices

    @staticmethod
    def _get_scsi_controller(image_meta):
        """Return scsi controller or None based on image meta"""
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

        if CONF.libvirt.sysinfo_serial == 'unique':
            sysinfo.system_serial = instance.uuid
        else:
            sysinfo.system_serial = self._sysinfo_serial_func()
        sysinfo.system_uuid = instance.uuid

        sysinfo.system_family = "Virtual Machine"

        return sysinfo

    def _set_managed_mode(self, pcidev):
        # only kvm support managed mode
        if CONF.libvirt.virt_type in ('parallels',):
            pcidev.managed = 'no'
        if CONF.libvirt.virt_type in ('kvm', 'qemu'):
            pcidev.managed = 'yes'

    def _get_guest_pci_device(self, pci_device):

        dbsf = pci_utils.parse_address(pci_device.address)
        dev = vconfig.LibvirtConfigGuestHostdevPCI()
        dev.domain, dev.bus, dev.slot, dev.function = dbsf
        self._set_managed_mode(dev)

        return dev

    def _get_guest_config_meta(self, instance, network_info):
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

        ports = []
        for vif in network_info:
            ips = []
            for subnet in vif.get('network', {}).get('subnets', []):
                for ip in subnet.get('ips', []):
                    ips.append(vconfig.LibvirtConfigGuestMetaNovaIp(
                        ip.get('type'), ip.get('address'), ip.get('version')))
            ports.append(vconfig.LibvirtConfigGuestMetaNovaPort(
                vif.get('id'), ips=ips))

        meta.ports = vconfig.LibvirtConfigGuestMetaNovaPorts(ports)

        return meta

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
        id_maps: ty.List[vconfig.LibvirtConfigGuestIDMap] = []
        if CONF.libvirt.virt_type == 'lxc' and CONF.libvirt.uid_maps:
            uid_maps = self._create_idmaps(vconfig.LibvirtConfigGuestUIDMap,
                                           CONF.libvirt.uid_maps)
            id_maps.extend(uid_maps)
        if CONF.libvirt.virt_type == 'lxc' and CONF.libvirt.gid_maps:
            gid_maps = self._create_idmaps(vconfig.LibvirtConfigGuestGIDMap,
                                           CONF.libvirt.gid_maps)
            id_maps.extend(gid_maps)
        return id_maps

    def _update_guest_cputune(self, guest, flavor):
        is_able = self._host.is_cpu_control_policy_capable()

        cputuning = ['shares', 'period', 'quota']
        wants_cputune = any([k for k in cputuning
            if "quota:cpu_" + k in flavor.extra_specs.keys()])

        if wants_cputune and not is_able:
            raise exception.UnsupportedHostCPUControlPolicy()

        if not is_able or CONF.libvirt.virt_type not in ('lxc', 'kvm', 'qemu'):
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
                guest_cell.cpus = instance_cell.total_cpus
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

    def _get_cell_pairs(self, guest_cpu_numa_config, host_topology):
        """Returns the lists of pairs(tuple) of an instance cell and
        corresponding host cell:
            [(LibvirtConfigGuestCPUNUMACell, NUMACell), ...]
        """
        cell_pairs = []
        for guest_config_cell in guest_cpu_numa_config.cells:
            for host_cell in host_topology.cells:
                if guest_config_cell.id == host_cell.id:
                    cell_pairs.append((guest_config_cell, host_cell))
        return cell_pairs

    def _get_pin_cpuset(self, vcpu, inst_cell, host_cell):
        """Returns the config object of LibvirtConfigGuestCPUTuneVCPUPin.

        Prepares vcpupin config for the guest with the following caveats:

            a) If the specified instance vCPU is intended to be pinned, we pin
               it to the previously selected host CPU.
            b) Otherwise we float over the whole host NUMA node
        """
        pin_cpuset = vconfig.LibvirtConfigGuestCPUTuneVCPUPin()
        pin_cpuset.id = vcpu

        # 'InstanceNUMACell.cpu_pinning' tracks the CPU pinning pair for guest
        # CPU and host CPU. If the guest CPU is in the keys of 'cpu_pinning',
        # fetch the host CPU from it and pin on it, otherwise, let the guest
        # CPU be floating on the sharing CPU set belonging to this NUMA cell.
        if inst_cell.cpu_pinning and vcpu in inst_cell.cpu_pinning:
            pin_cpuset.cpuset = set([inst_cell.cpu_pinning[vcpu]])
        else:
            pin_cpuset.cpuset = host_cell.cpuset

        return pin_cpuset

    def _get_emulatorpin_cpuset(self, vcpu, object_numa_cell, vcpus_rt,
                                emulator_threads_policy,
                                pin_cpuset):
        """Returns a set of cpu_ids to add to the cpuset for emulator threads
           with the following caveats:

            a) If emulator threads policy is isolated, we pin emulator threads
               to one cpu we have reserved for it.
            b) If emulator threads policy is shared and CONF.cpu_shared_set is
               defined, we pin emulator threads on the set of pCPUs defined by
               CONF.cpu_shared_set
            c) Otherwise;
                c1) If realtime IS NOT enabled, the emulator threads are
                    allowed to float cross all the pCPUs associated with
                    the guest vCPUs.
                c2) If realtime IS enabled, at least 1 vCPU is required
                    to be set aside for non-realtime usage. The emulator
                    threads are allowed to float across the pCPUs that
                    are associated with the non-realtime VCPUs.
        """
        emulatorpin_cpuset = set([])
        shared_ids = hardware.get_cpu_shared_set()

        if emulator_threads_policy == fields.CPUEmulatorThreadsPolicy.ISOLATE:
            if object_numa_cell.cpuset_reserved:
                emulatorpin_cpuset = object_numa_cell.cpuset_reserved
        elif ((emulator_threads_policy ==
              fields.CPUEmulatorThreadsPolicy.SHARE) and
              shared_ids):
            online_pcpus = self._host.get_online_cpus()
            cpuset = shared_ids & online_pcpus
            if not cpuset:
                msg = (_("Invalid cpu_shared_set config, one or more of the "
                         "specified cpuset is not online. Online cpuset(s): "
                         "%(online)s, requested cpuset(s): %(req)s"),
                       {'online': sorted(online_pcpus),
                        'req': sorted(shared_ids)})
                raise exception.Invalid(msg)
            emulatorpin_cpuset = cpuset
        elif not vcpus_rt or vcpu not in vcpus_rt:
            emulatorpin_cpuset = pin_cpuset.cpuset

        return emulatorpin_cpuset

    def _get_guest_numa_config(self, instance_numa_topology, flavor,
                               image_meta):
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
               allowed CPUs fit within.

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

        # We only pin an instance to some host cores if the user has provided
        # configuration to suggest we should.
        shared_cpus = None
        if CONF.vcpu_pin_set or CONF.compute.cpu_shared_set:
            shared_cpus = self._get_vcpu_available()

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
            return GuestNumaConfig(shared_cpus, None, None, None)

        if not topology:
            # No NUMA topology defined for host - This will only happen with
            # some libvirt versions and certain platforms.
            return GuestNumaConfig(shared_cpus, None,
                                   guest_cpu_numa_config, None)

        # Now get configuration from the numa_topology
        # Init CPUTune configuration
        guest_cpu_tune = vconfig.LibvirtConfigGuestCPUTune()
        guest_cpu_tune.emulatorpin = (
            vconfig.LibvirtConfigGuestCPUTuneEmulatorPin())
        guest_cpu_tune.emulatorpin.cpuset = set([])

        # Init NUMATune configuration
        guest_numa_tune = vconfig.LibvirtConfigGuestNUMATune()
        guest_numa_tune.memory = vconfig.LibvirtConfigGuestNUMATuneMemory()
        guest_numa_tune.memnodes = []

        emulator_threads_policy = None
        if 'emulator_threads_policy' in instance_numa_topology:
            emulator_threads_policy = (
                instance_numa_topology.emulator_threads_policy)

        # Set realtime scheduler for CPUTune
        vcpus_rt = hardware.get_realtime_cpu_constraint(flavor, image_meta)
        if vcpus_rt:
            vcpusched = vconfig.LibvirtConfigGuestCPUTuneVCPUSched()
            designer.set_vcpu_realtime_scheduler(
                vcpusched, vcpus_rt, CONF.libvirt.realtime_scheduler_priority)
            guest_cpu_tune.vcpusched.append(vcpusched)

        cell_pairs = self._get_cell_pairs(guest_cpu_numa_config, topology)
        for guest_node_id, (guest_config_cell, host_cell) in enumerate(
                cell_pairs):
            # set NUMATune for the cell
            tnode = vconfig.LibvirtConfigGuestNUMATuneMemNode()
            designer.set_numa_memnode(tnode, guest_node_id, host_cell.id)
            guest_numa_tune.memnodes.append(tnode)
            guest_numa_tune.memory.nodeset.append(host_cell.id)

            # set CPUTune for the cell
            object_numa_cell = instance_numa_topology.cells[guest_node_id]
            for cpu in guest_config_cell.cpus:
                pin_cpuset = self._get_pin_cpuset(cpu, object_numa_cell,
                                                  host_cell)
                guest_cpu_tune.vcpupin.append(pin_cpuset)

                emu_pin_cpuset = self._get_emulatorpin_cpuset(
                    cpu, object_numa_cell, vcpus_rt,
                    emulator_threads_policy, pin_cpuset)
                guest_cpu_tune.emulatorpin.cpuset.update(emu_pin_cpuset)

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

        # Sort the vcpupin list per vCPU id for human-friendlier XML
        guest_cpu_tune.vcpupin.sort(key=operator.attrgetter("id"))

        # normalize cell.id
        for i, (cell, memnode) in enumerate(zip(guest_cpu_numa_config.cells,
                                                guest_numa_tune.memnodes)):
            cell.id = i
            memnode.cellid = i

        return GuestNumaConfig(None, guest_cpu_tune, guest_cpu_numa_config,
                               guest_numa_tune)

    def _get_guest_os_type(self):
        """Returns the guest OS type based on virt type."""
        if CONF.libvirt.virt_type == "lxc":
            ret = fields.VMMode.EXE
        else:
            ret = fields.VMMode.HVM
        return ret

    def _set_guest_for_rescue(
        self, rescue, guest, inst_path, root_device_name,
    ):
        if rescue.get('kernel_id'):
            guest.os_kernel = os.path.join(inst_path, "kernel.rescue")
            guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
            if CONF.libvirt.virt_type == "qemu":
                guest.os_cmdline += " no_timer_check"
        if rescue.get('ramdisk_id'):
            guest.os_initrd = os.path.join(inst_path, "ramdisk.rescue")

    def _set_guest_for_inst_kernel(
        self, instance, guest, inst_path, root_device_name, image_meta,
    ):
        guest.os_kernel = os.path.join(inst_path, "kernel")
        guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
        if CONF.libvirt.virt_type == "qemu":
            guest.os_cmdline += " no_timer_check"
        if instance.ramdisk_id:
            guest.os_initrd = os.path.join(inst_path, "ramdisk")
        # we only support os_command_line with images with an explicit
        # kernel set and don't want to break nova if there's an
        # os_command_line property without a specified kernel_id param
        if image_meta.properties.get("os_command_line"):
            guest.os_cmdline = image_meta.properties.os_command_line

    def _set_clock(self, guest, os_type, image_meta):
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

        if CONF.libvirt.virt_type == "kvm":
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

        hpet = image_meta.properties.get('hw_time_hpet', False)
        guestarch = libvirt_utils.get_arch(image_meta)
        if guestarch in (fields.Architecture.I686,
                         fields.Architecture.X86_64):
            # NOTE(rfolco): HPET is a hardware timer for x86 arch.
            # qemu -no-hpet is not supported on non-x86 targets.
            tmhpet = vconfig.LibvirtConfigGuestTimer()
            tmhpet.name = "hpet"
            tmhpet.present = hpet
            clk.add_timer(tmhpet)
        else:
            if hpet:
                LOG.warning('HPET is not turned on for non-x86 guests in image'
                            ' %s.', image_meta.id)

        # Provide Windows guests with the paravirtualized hyperv timer source.
        # This is the windows equiv of kvm-clock, allowing Windows
        # guests to accurately keep time.
        if os_type == 'windows':
            tmhyperv = vconfig.LibvirtConfigGuestTimer()
            tmhyperv.name = "hypervclock"
            tmhyperv.present = True
            clk.add_timer(tmhyperv)

    def _set_features(self, guest, os_type, image_meta, flavor):
        hide_hypervisor_id = (strutils.bool_from_string(
                flavor.extra_specs.get('hide_hypervisor_id')) or
                strutils.bool_from_string(
                    flavor.extra_specs.get('hw:hide_hypervisor_id')) or
                image_meta.properties.get('img_hide_hypervisor_id'))

        if CONF.libvirt.virt_type in ('qemu', 'kvm'):
            guest.features.append(vconfig.LibvirtConfigGuestFeatureACPI())
            if not CONF.workarounds.libvirt_disable_apic:
                guest.features.append(vconfig.LibvirtConfigGuestFeatureAPIC())

        if CONF.libvirt.virt_type in ('qemu', 'kvm') and os_type == 'windows':
            hv = vconfig.LibvirtConfigGuestFeatureHyperV()
            hv.relaxed = True

            hv.spinlocks = True
            # Increase spinlock retries - value recommended by
            # KVM maintainers who certify Windows guests
            # with Microsoft
            hv.spinlock_retries = 8191
            hv.vapic = True

            # NOTE(kosamara): Spoofing the vendor_id aims to allow the nvidia
            # driver to work on windows VMs. At the moment, the nvidia driver
            # checks for the hyperv vendorid, and if it doesn't find that, it
            # works. In the future, its behaviour could become more strict,
            # checking for the presence of other hyperv feature flags to
            # determine that it's loaded in a VM. If that happens, this
            # workaround will not be enough, and we'll need to drop the whole
            # hyperv element.
            # That would disable some optimizations, reducing the guest's
            # performance.
            if hide_hypervisor_id:
                hv.vendorid_spoof = True

            guest.features.append(hv)

        if CONF.libvirt.virt_type in ("qemu", "kvm"):
            # vmcoreinfo support is x86, ARM-only for now
            guestarch = libvirt_utils.get_arch(image_meta)
            if guestarch in (
                fields.Architecture.I686, fields.Architecture.X86_64,
                fields.Architecture.AARCH64,
            ):
                guest.features.append(
                    vconfig.LibvirtConfigGuestFeatureVMCoreInfo())

            if hide_hypervisor_id:
                guest.features.append(
                    vconfig.LibvirtConfigGuestFeatureKvmHidden())

            # NOTE(sean-k-mooney): we validate that the image and flavor
            # cannot have conflicting values in the compute API
            # so we just use the values directly. If it is not set in
            # either the flavor or image pmu will be none and we should
            # not generate the element to allow qemu to decide if a vPMU
            # should be provided for backwards compatibility.
            pmu = (flavor.extra_specs.get('hw:pmu') or
                   image_meta.properties.get('hw_pmu'))
            if pmu is not None:
                guest.features.append(
                    vconfig.LibvirtConfigGuestFeaturePMU(pmu))

    def _check_number_of_serial_console(self, num_ports):
        if (
            CONF.libvirt.virt_type in ("kvm", "qemu") and
            num_ports > ALLOWED_QEMU_SERIAL_PORTS
        ):
            raise exception.SerialPortNumberLimitExceeded(
                allowed=ALLOWED_QEMU_SERIAL_PORTS,
                virt_type=CONF.libvirt.virt_type)

    def _video_model_supported(self, model):
        return model in fields.VideoModel.ALL

    def _add_video_driver(self, guest, image_meta, flavor):
        video = vconfig.LibvirtConfigGuestVideo()
        video.type = self._get_video_type(image_meta) or video.type
        # Set video memory, only if the flavor's limit is set
        video_ram = image_meta.properties.get('hw_video_ram', 0)
        max_vram = int(flavor.extra_specs.get('hw_video:ram_max_mb', 0))
        if video_ram > max_vram:
            raise exception.RequestedVRamTooHigh(req_vram=video_ram,
                                                 max_vram=max_vram)
        if max_vram and video_ram:
            video.vram = video_ram * units.Mi // units.Ki
        guest.add_device(video)

        # NOTE(sean-k-mooney): return the video device we added
        # for simpler testing.
        return video

    def _get_video_type(
        self,
        image_meta: objects.ImageMeta,
    ) -> ty.Optional[str]:
        # NOTE(ldbragst): The following logic returns the video type
        # depending on supported defaults given the architecture,
        # virtualization type, and features. The video type can
        # be overridden by the user with image_meta.properties, which
        # is carried out first.
        if image_meta.properties.get('hw_video_model'):
            video_type = image_meta.properties.hw_video_model
            if not self._video_model_supported(video_type):
                raise exception.InvalidVideoMode(model=video_type)
            return video_type

        guestarch = libvirt_utils.get_arch(image_meta)

        if CONF.libvirt.virt_type == 'parallels':
            return 'vga'

        if (
            guestarch in (
                fields.Architecture.I686,
                fields.Architecture.X86_64
            ) and not CONF.spice.enabled
        ):
            return 'virtio'

        if (
            guestarch in (
                fields.Architecture.PPC,
                fields.Architecture.PPC64,
                fields.Architecture.PPC64LE
            )
        ):
            # NOTE(ldbragst): PowerKVM doesn't support 'cirrus' be default
            # so use 'vga' instead when running on Power hardware.
            return 'vga'

        if guestarch == fields.Architecture.AARCH64:
            # NOTE(kevinz): Only virtio device type is supported by AARCH64
            # so use 'virtio' instead when running on AArch64 hardware.
            return 'virtio'

        if CONF.spice.enabled:
            return 'qxl'

        # NOTE(lyarwood): Return None and default to the default of
        # LibvirtConfigGuestVideo.type that is currently virtio
        return None

    def _add_qga_device(self, guest, instance):
        qga = vconfig.LibvirtConfigGuestChannel()
        qga.type = "unix"
        qga.target_name = "org.qemu.guest_agent.0"
        qga.source_path = ("/var/lib/libvirt/qemu/%s.%s.sock" %
                          ("org.qemu.guest_agent.0", instance.name))
        guest.add_device(qga)

    def _add_rng_device(self, guest, flavor, image_meta):
        rng_allowed_str = flavor.extra_specs.get('hw_rng:allowed', 'True')
        rng_allowed = strutils.bool_from_string(rng_allowed_str)

        if not rng_allowed:
            return

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

    def _add_virtio_serial_controller(self, guest, instance):
        virtio_controller = vconfig.LibvirtConfigGuestController()
        virtio_controller.type = 'virtio-serial'
        guest.add_device(virtio_controller)

    def _add_vtpm_device(
        self,
        guest: vconfig.LibvirtConfigGuest,
        flavor: 'objects.Flavor',
        instance: 'objects.Instance',
        image_meta: 'objects.ImageMeta',
    ) -> None:
        """Add a vTPM device to the guest, if requested."""
        # Enable virtual tpm support if required in the flavor or image.
        vtpm_config = hardware.get_vtpm_constraint(flavor, image_meta)
        if not vtpm_config:
            return None

        vtpm_secret_uuid = instance.system_metadata.get('vtpm_secret_uuid')
        if not vtpm_secret_uuid:
            raise exception.Invalid(
                'Refusing to create an emulated TPM with no secret!')

        vtpm = vconfig.LibvirtConfigGuestVTPM(vtpm_config, vtpm_secret_uuid)
        guest.add_device(vtpm)

    def _set_qemu_guest_agent(self, guest, flavor, instance, image_meta):
        # Enable qga only if the 'hw_qemu_guest_agent' is equal to yes
        if image_meta.properties.get('hw_qemu_guest_agent', False):
            # a virtio-serial controller is required for qga. If it is not
            # created explicitly, libvirt will do it by itself. But in case
            # of AMD SEV, any virtio device should use iommu driver, and
            # libvirt does not know about it. That is why the controller
            # should be created manually.
            if self._sev_enabled(flavor, image_meta):
                self._add_virtio_serial_controller(guest, instance)

            LOG.debug("Qemu guest agent is enabled through image "
                      "metadata", instance=instance)
            self._add_qga_device(guest, instance)

    def _get_guest_memory_backing_config(
            self, inst_topology, numatune, flavor, image_meta):
        wantsrealtime = hardware.is_realtime_enabled(flavor)
        if (
            wantsrealtime and
            hardware.get_emulator_thread_policy_constraint(flavor) ==
                fields.CPUEmulatorThreadsPolicy.SHARE and
            not CONF.compute.cpu_shared_set
        ):
            # NOTE(stephenfin) Yes, it's horrible that we're doing this here,
            # but the shared policy unfortunately has different behavior
            # depending on whether the '[compute] cpu_shared_set' is configured
            # or not and we need it to be configured. Also note that we have
            # already handled other conditions, such as no emulator thread
            # policy being configured whatsoever, at the API level.
            LOG.warning(
                'Instance is requesting real-time CPUs with pooled '
                'emulator threads, but a shared CPU pool has not been '
                'configured on this host.'
            )
            raise exception.RealtimeMaskNotFoundOrInvalid()

        wantsmempages = False
        if inst_topology:
            for cell in inst_topology.cells:
                if cell.pagesize:
                    wantsmempages = True
                    break

        wantsfilebacked = CONF.libvirt.file_backed_memory > 0

        if wantsmempages and wantsfilebacked:
            # Can't use file-backed memory with hugepages
            LOG.warning("Instance requested huge pages, but file-backed "
                    "memory is enabled, and incompatible with huge pages")
            raise exception.MemoryPagesUnsupported()

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
        if wantsfilebacked:
            if not membacking:
                membacking = vconfig.LibvirtConfigGuestMemoryBacking()
            membacking.filesource = True
            membacking.sharedaccess = True
            membacking.allocateimmediate = True
            membacking.discard = True
        if self._sev_enabled(flavor, image_meta):
            if not membacking:
                membacking = vconfig.LibvirtConfigGuestMemoryBacking()
            membacking.locked = True

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

    def _check_uefi_support(self, hw_firmware_type):
        caps = self._host.get_capabilities()
        return self._host.supports_uefi and (
            hw_firmware_type == fields.FirmwareType.UEFI or
            caps.host.cpu.arch == fields.Architecture.AARCH64
        )

    def _check_secure_boot_support(
        self,
        arch: str,
        machine_type: str,
        firmware_type: str,
    ) -> bool:
        if not self._host.supports_secure_boot:
            # secure boot requires host configuration
            return False

        if firmware_type != fields.FirmwareType.UEFI:
            # secure boot is only supported with UEFI
            return False

        if (
            arch == fields.Architecture.X86_64 and
            'q35' not in machine_type
        ):
            # secure boot on x86_64 requires the Q35 machine type
            return False

        return True

    def _get_supported_perf_events(self):
        if not len(CONF.libvirt.enabled_perf_events):
            return []

        supported_events = []
        for event in CONF.libvirt.enabled_perf_events:
            libvirt_perf_event_name = LIBVIRT_PERF_EVENT_PREFIX + event.upper()

            if not hasattr(libvirt, libvirt_perf_event_name):
                LOG.warning("Libvirt does not support event type '%s'.", event)
                continue

            if event in ('cmt', 'mbml', 'mbmt'):
                LOG.warning(
                    "Monitoring of Intel CMT `perf` event(s) '%s' is not "
                    "supported by recent Linux kernels; ignoring.",
                    event,
                )
                continue

            supported_events.append(event)

        return supported_events

    def _configure_guest_by_virt_type(
        self,
        guest: vconfig.LibvirtConfigGuest,
        instance: 'objects.Instance',
        image_meta: 'objects.ImageMeta',
        flavor: 'objects.Flavor',
    ) -> None:
        if CONF.libvirt.virt_type in ("kvm", "qemu"):
            arch = libvirt_utils.get_arch(image_meta)
            if arch in (fields.Architecture.I686, fields.Architecture.X86_64):
                guest.sysinfo = self._get_guest_config_sysinfo(instance)
                guest.os_smbios = vconfig.LibvirtConfigGuestSMBIOS()

            mach_type = libvirt_utils.get_machine_type(image_meta)
            guest.os_mach_type = mach_type

            hw_firmware_type = image_meta.properties.get('hw_firmware_type')

            if arch == fields.Architecture.AARCH64:
                if not hw_firmware_type:
                    hw_firmware_type = fields.FirmwareType.UEFI

            if hw_firmware_type == fields.FirmwareType.UEFI:
                global uefi_logged
                if not uefi_logged:
                    LOG.warning("uefi support is without some kind of "
                                "functional testing and therefore "
                                "considered experimental.")
                    uefi_logged = True

                if not self._host.supports_uefi:
                    raise exception.UEFINotSupported()

                # TODO(stephenfin): Drop this when we drop support for legacy
                # architectures
                if not mach_type:
                    # loaders are specific to arch and machine type - if we
                    # don't have a machine type here, we're on a legacy
                    # architecture that we have no default machine type for
                    raise exception.UEFINotSupported()

                os_secure_boot = hardware.get_secure_boot_constraint(
                    flavor, image_meta)
                if os_secure_boot == 'required':
                    # hard fail if we don't support secure boot and it's
                    # required
                    if not self._check_secure_boot_support(
                        arch, mach_type, hw_firmware_type,
                    ):
                        raise exception.SecureBootNotSupported()

                    guest.os_loader_secure = True
                elif os_secure_boot == 'optional':
                    # only enable it if the host is configured appropriately
                    guest.os_loader_secure = self._check_secure_boot_support(
                        arch, mach_type, hw_firmware_type,
                    )
                else:
                    guest.os_loader_secure = False

                try:
                    loader, nvram_template = self._host.get_loader(
                        arch, mach_type,
                        has_secure_boot=guest.os_loader_secure)
                except exception.UEFINotSupported as exc:
                    if guest.os_loader_secure:
                        # we raise a specific exception if we requested secure
                        # boot and couldn't get that
                        raise exception.SecureBootNotSupported() from exc
                    raise

                guest.os_loader = loader
                guest.os_loader_type = 'pflash'
                guest.os_nvram_template = nvram_template

            # NOTE(lyarwood): If the machine type isn't recorded in the stashed
            # image metadata then record it through the system metadata table.
            # This will allow the host configuration to change in the future
            # without impacting existing instances.
            # NOTE(lyarwood): The value of ``hw_machine_type`` within the
            # stashed image metadata of the instance actually comes from the
            # system metadata table under the ``image_hw_machine_type`` key via
            # nova.objects.ImageMeta.from_instance and the
            # nova.utils.get_image_from_system_metadata function.
            if image_meta.properties.get('hw_machine_type') is None:
                instance.system_metadata['image_hw_machine_type'] = mach_type

            if image_meta.properties.get('hw_boot_menu') is None:
                guest.os_bootmenu = strutils.bool_from_string(
                    flavor.extra_specs.get('hw:boot_menu', 'no'))
            else:
                guest.os_bootmenu = image_meta.properties.hw_boot_menu
        elif CONF.libvirt.virt_type == "lxc":
            guest.os_init_path = "/sbin/init"
            guest.os_cmdline = CONSOLE
            guest.os_init_env["product_name"] = "OpenStack Nova"
        elif CONF.libvirt.virt_type == "parallels":
            if guest.os_type == fields.VMMode.EXE:
                guest.os_init_path = "/sbin/init"

        return None

    def _conf_non_lxc(
        self,
        guest: vconfig.LibvirtConfigGuest,
        root_device_name: str,
        rescue: bool,
        instance: 'objects.Instance',
        inst_path: str,
        image_meta: 'objects.ImageMeta',
        disk_info: ty.Dict[str, ty.Any],
    ):
        if rescue:
            self._set_guest_for_rescue(
                rescue, guest, inst_path, root_device_name)
        elif instance.kernel_id:
            self._set_guest_for_inst_kernel(
                instance, guest, inst_path, root_device_name, image_meta)
        else:
            guest.os_boot_dev = blockinfo.get_boot_order(disk_info)

    def _create_consoles(self, guest_cfg, instance, flavor, image_meta):
        # NOTE(markus_z): Beware! Below are so many conditionals that it is
        # easy to lose track. Use this chart to figure out your case:
        #
        # case | is serial | is qemu | resulting
        #      | enabled?  | or kvm? | devices
        # -------------------------------------------
        #    1 |        no |     no  | pty*
        #    2 |        no |     yes | pty with logd
        #    3 |       yes |      no | see case 1
        #    4 |       yes |     yes | tcp with logd
        #
        #    * exception: `virt_type=parallels` doesn't create a device
        if CONF.libvirt.virt_type == 'parallels':
            pass
        elif CONF.libvirt.virt_type == 'lxc':
            log_path = self._get_console_log_path(instance)
            self._create_pty_device(
                guest_cfg, vconfig.LibvirtConfigGuestConsole,
                log_path=log_path)
        else:  # qemu, kvm
            if self._is_s390x_guest(image_meta):
                self._create_consoles_s390x(
                    guest_cfg, instance, flavor, image_meta)
            else:
                self._create_consoles_qemu_kvm(
                    guest_cfg, instance, flavor, image_meta)

    def _is_s390x_guest(self, image_meta):
        s390x_archs = (fields.Architecture.S390, fields.Architecture.S390X)
        return libvirt_utils.get_arch(image_meta) in s390x_archs

    def _is_ppc64_guest(self, image_meta):
        archs = (fields.Architecture.PPC64, fields.Architecture.PPC64LE)
        return libvirt_utils.get_arch(image_meta) in archs

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
            self._create_pty_device(guest_cfg, char_dev_cls,
                                    log_path=log_path)

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
            self._create_pty_device(guest_cfg, char_dev_cls,
                                    "sclp", log_path)

    def _create_pty_device(self, guest_cfg, char_dev_cls, target_type=None,
                           log_path=None):

        consolepty = char_dev_cls()
        consolepty.target_type = target_type
        consolepty.type = "pty"

        log = vconfig.LibvirtConfigGuestCharDeviceLog()
        log.file = log_path
        consolepty.log = log

        guest_cfg.add_device(consolepty)

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
        for port in range(num_ports):
            console = char_dev_cls()
            console.port = port
            console.type = "tcp"
            console.listen_host = CONF.serial_console.proxyclient_address
            listen_port = serial_console.acquire_port(console.listen_host)
            console.listen_port = listen_port
            # NOTE: only the first serial console gets the boot messages,
            # that's why we attach the logd subdevice only to that.
            if port == 0:
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

    def _guest_needs_usb(self, guest, image_meta):
        """Evaluate devices currently attached to the guest."""
        if self._is_ppc64_guest(image_meta):
            # PPC64 guests get a USB keyboard and mouse automatically
            return True

        for dev in guest.devices:
            if isinstance(dev, vconfig.LibvirtConfigGuestDisk):
                if dev.target_bus == 'usb':
                    return True

            if isinstance(dev, vconfig.LibvirtConfigGuestInput):
                if dev.bus == 'usb':
                    return True

        return False

    def _guest_add_usb_root_controller(self, guest, image_meta):
        """Add USB root controller, if necessary.

        Note that these are added by default on x86-64. We add the controller
        here explicitly so that we can _disable_ it (by setting the model to
        'none') if it's not necessary.
        """
        usbhost = vconfig.LibvirtConfigGuestUSBHostController()
        usbhost.index = 0
        # an unset model means autodetect, while 'none' means don't add a
        # controller (x86 gets one by default)
        usbhost.model = None
        if not self._guest_needs_usb(guest, image_meta):
            usbhost.model = 'none'
        guest.add_device(usbhost)

    def _guest_add_pcie_root_ports(self, guest):
        """Add PCI Express root ports.

        PCI Express machine can have as many PCIe devices as it has
        pcie-root-port controllers (slots in virtual motherboard).

        If we want to have more PCIe slots for hotplug then we need to create
        whole PCIe structure (libvirt limitation).
        """

        pcieroot = vconfig.LibvirtConfigGuestPCIeRootController()
        guest.add_device(pcieroot)

        for x in range(0, CONF.libvirt.num_pcie_ports):
            pcierootport = vconfig.LibvirtConfigGuestPCIeRootPortController()
            guest.add_device(pcierootport)

    def _guest_needs_pcie(self, guest):
        """Check for prerequisites for adding PCIe root port
        controllers
        """
        caps = self._host.get_capabilities()

        # TODO(kchamart) In the third 'if' conditional below, for 'x86'
        # arch, we're assuming: when 'os_mach_type' is 'None', you'll
        # have "pc" machine type.  That assumption, although it is
        # correct for the "forseeable future", it will be invalid when
        # libvirt / QEMU changes the default machine types.
        #
        # From libvirt 4.7.0 onwards (September 2018), it will ensure
        # that *if* 'pc' is available, it will be used as the default --
        # to not break existing applications.  (Refer:
        # https://libvirt.org/git/?p=libvirt.git;a=commit;h=26cfb1a3
        # --"qemu: ensure default machine types don't change if QEMU
        # changes").
        #
        # But even if libvirt (>=v4.7.0) handled the default case,
        # relying on such assumptions is not robust.  Instead we should
        # get the default machine type for a given architecture reliably
        # -- by Nova setting it explicitly (we already do it for Arm /
        # AArch64 & s390x).  A part of this bug is being tracked here:
        # https://bugs.launchpad.net/nova/+bug/1780138).

        # Add PCIe root port controllers for PCI Express machines
        # but only if their amount is configured

        if not CONF.libvirt.num_pcie_ports:
            return False
        if (caps.host.cpu.arch == fields.Architecture.AARCH64 and
                guest.os_mach_type.startswith('virt')):
            return True
        if (caps.host.cpu.arch == fields.Architecture.X86_64 and
                guest.os_mach_type is not None and
                'q35' in guest.os_mach_type):
            return True
        return False

    def _get_guest_config(self, instance, network_info, image_meta,
                          disk_info, rescue=None, block_device_info=None,
                          context=None, mdevs=None, accel_info=None):
        """Get config data for parameters.

        :param rescue: optional dictionary that should contain the key
            'ramdisk_id' if a ramdisk is needed for the rescue image and
            'kernel_id' if a kernel is needed for the rescue image.

        :param mdevs: optional list of mediated devices to assign to the guest.
        :param accel_info: optional list of accelerator requests (ARQs)
        """
        flavor = instance.flavor
        inst_path = libvirt_utils.get_instance_path(instance)
        disk_mapping = disk_info['mapping']
        vpmems = self._get_ordered_vpmems(instance, flavor)

        guest = vconfig.LibvirtConfigGuest()
        guest.virt_type = CONF.libvirt.virt_type
        guest.name = instance.name
        guest.uuid = instance.uuid
        # We are using default unit for memory: KiB
        guest.memory = flavor.memory_mb * units.Ki
        guest.vcpus = flavor.vcpus

        guest_numa_config = self._get_guest_numa_config(
            instance.numa_topology, flavor, image_meta)

        guest.cpuset = guest_numa_config.cpuset
        guest.cputune = guest_numa_config.cputune
        guest.numatune = guest_numa_config.numatune

        guest.membacking = self._get_guest_memory_backing_config(
            instance.numa_topology,
            guest_numa_config.numatune,
            flavor, image_meta)

        guest.metadata.append(self._get_guest_config_meta(
            instance, network_info))
        guest.idmaps = self._get_guest_idmaps()

        for event in self._supported_perf_events:
            guest.add_perf_event(event)

        self._update_guest_cputune(guest, flavor)

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

        guest.os_type = (
            fields.VMMode.get_from_instance(instance) or
            self._get_guest_os_type()
        )

        sev_enabled = self._sev_enabled(flavor, image_meta)

        self._configure_guest_by_virt_type(guest, instance, image_meta, flavor)
        if CONF.libvirt.virt_type != 'lxc':
            self._conf_non_lxc(
                guest, root_device_name, rescue, instance, inst_path,
                image_meta, disk_info)

        self._set_features(guest, instance.os_type, image_meta, flavor)
        self._set_clock(guest, instance.os_type, image_meta)

        storage_configs = self._get_guest_storage_config(context,
                instance, image_meta, disk_info, rescue, block_device_info,
                flavor, guest.os_type)
        for config in storage_configs:
            guest.add_device(config)

        for vif in network_info:
            config = self.vif_driver.get_config(
                instance, vif, image_meta, flavor, CONF.libvirt.virt_type,
            )
            guest.add_device(config)

        self._create_consoles(guest, instance, flavor, image_meta)

        self._guest_add_spice_channel(guest)

        if self._guest_add_video_device(guest):
            self._add_video_driver(guest, image_meta, flavor)

            self._guest_add_pointer_device(guest, image_meta)
            self._guest_add_keyboard_device(guest, image_meta)

        # Some features are only supported 'qemu' and 'kvm' hypervisor
        if CONF.libvirt.virt_type in ('qemu', 'kvm'):
            self._set_qemu_guest_agent(guest, flavor, instance, image_meta)
            self._add_rng_device(guest, flavor, image_meta)
            self._add_vtpm_device(guest, flavor, instance, image_meta)

        if self._guest_needs_pcie(guest):
            self._guest_add_pcie_root_ports(guest)

        self._guest_add_usb_root_controller(guest, image_meta)

        self._guest_add_pci_devices(guest, instance)

        pci_arq_list = []
        if accel_info:
            # NOTE(Sundar): We handle only the case where all attach handles
            # are of type 'PCI'. The Cyborg fake driver used for testing
            # returns attach handles of type 'TEST_PCI' and so its ARQs will
            # not get composed into the VM's domain XML. For now, we do not
            # expect a mixture of different attach handles for the same
            # instance; but that case also gets ignored by this logic.
            ah_types_set = {arq['attach_handle_type'] for arq in accel_info}
            supported_types_set = {'PCI'}
            if ah_types_set == supported_types_set:
                pci_arq_list = accel_info
            else:
                LOG.info('Ignoring accelerator requests for instance %s. '
                         'Supported Attach handle types: %s. '
                         'But got these unsupported types: %s.',
                         instance.uuid, supported_types_set,
                         ah_types_set.difference(supported_types_set))

        self._guest_add_accel_pci_devices(guest, pci_arq_list)

        self._guest_add_watchdog_action(guest, flavor, image_meta)

        self._guest_add_memory_balloon(guest)

        if mdevs:
            self._guest_add_mdevs(guest, mdevs)

        if sev_enabled:
            caps = self._host.get_capabilities()
            self._guest_configure_sev(guest, caps.host.cpu.arch,
                                      guest.os_mach_type)

        if vpmems:
            self._guest_add_vpmems(guest, vpmems)

        return guest

    def _get_ordered_vpmems(self, instance, flavor):
        resources = self._get_resources(instance)
        ordered_vpmem_resources = self._get_ordered_vpmem_resources(
            resources, flavor)
        ordered_vpmems = [self._vpmems_by_name[resource.identifier]
            for resource in ordered_vpmem_resources]
        return ordered_vpmems

    def _get_vpmems(self, instance, prefix=None):
        resources = self._get_resources(instance, prefix=prefix)
        vpmem_resources = self._get_vpmem_resources(resources)
        vpmems = [self._vpmems_by_name[resource.identifier]
            for resource in vpmem_resources]
        return vpmems

    def _guest_add_vpmems(self, guest, vpmems):
        guest.max_memory_size = guest.memory
        guest.max_memory_slots = 0
        for vpmem in vpmems:
            size_kb = vpmem.size // units.Ki
            align_kb = vpmem.align // units.Ki

            vpmem_config = vconfig.LibvirtConfigGuestVPMEM(
                devpath=vpmem.devpath, size_kb=size_kb, align_kb=align_kb)

            # max memory size needs contain vpmem size
            guest.max_memory_size += size_kb
            # one vpmem will occupy one memory slot
            guest.max_memory_slots += 1
            guest.add_device(vpmem_config)

    def _sev_enabled(self, flavor, image_meta):
        """To enable AMD SEV, the following should be true:

        a) the supports_amd_sev instance variable in the host is
           true,
        b) the instance extra specs and/or image properties request
           memory encryption to be enabled, and
        c) there are no conflicts between extra specs, image properties
           and machine type selection.

        Most potential conflicts in c) should already be caught in the
        API layer.  However there is still one remaining case which
        needs to be handled here: when the image does not contain an
        hw_machine_type property, the machine type will be chosen from
        CONF.libvirt.hw_machine_type if configured, otherwise falling
        back to the hardcoded value which is currently 'pc'.  If it
        ends up being 'pc' or another value not in the q35 family, we
        need to raise an exception.  So calculate the machine type and
        pass it to be checked alongside the other sanity checks which
        are run while determining whether SEV is selected.
        """
        if not self._host.supports_amd_sev:
            return False

        mach_type = libvirt_utils.get_machine_type(image_meta)
        return hardware.get_mem_encryption_constraint(flavor, image_meta,
                                                      mach_type)

    def _guest_configure_sev(self, guest, arch, mach_type):
        sev = self._find_sev_feature(arch, mach_type)
        if sev is None:
            # In theory this should never happen because it should
            # only get called if SEV was requested, in which case the
            # guest should only get scheduled on this host if it
            # supports SEV, and SEV support is dependent on the
            # presence of this <sev> feature.  That said, it's
            # conceivable that something could get messed up along the
            # way, e.g. a mismatch in the choice of machine type.  So
            # make sure that if it ever does happen, we at least get a
            # helpful error rather than something cryptic like
            # "AttributeError: 'NoneType' object has no attribute 'cbitpos'
            raise exception.MissingDomainCapabilityFeatureException(
                feature='sev')

        designer.set_driver_iommu_for_all_devices(guest)
        self._guest_add_launch_security(guest, sev)

    def _guest_add_launch_security(self, guest, sev):
        launch_security = vconfig.LibvirtConfigGuestSEVLaunchSecurity()
        launch_security.cbitpos = sev.cbitpos
        launch_security.reduced_phys_bits = sev.reduced_phys_bits
        guest.launch_security = launch_security

    def _find_sev_feature(self, arch, mach_type):
        """Search domain capabilities for the given arch and machine type
        for the <sev> element under <features>, and return it if found.
        """
        domain_caps = self._host.get_domain_capabilities()
        if arch not in domain_caps:
            LOG.warning(
                "Wanted to add SEV to config for guest with arch %(arch)s "
                "but only had domain capabilities for: %(archs)s",
                {'arch': arch, 'archs': ' '.join(domain_caps)})
            return None

        if mach_type not in domain_caps[arch]:
            LOG.warning(
                "Wanted to add SEV to config for guest with machine type "
                "%(mtype)s but for arch %(arch)s only had domain capabilities "
                "for machine types: %(mtypes)s",
                {'mtype': mach_type, 'arch': arch,
                 'mtypes': ' '.join(domain_caps[arch])})
            return None

        for feature in domain_caps[arch][mach_type].features:
            if feature.root_name == 'sev':
                return feature

        return None

    def _guest_add_mdevs(self, guest, chosen_mdevs):
        for chosen_mdev in chosen_mdevs:
            mdev = vconfig.LibvirtConfigGuestHostdevMDEV()
            mdev.uuid = chosen_mdev
            guest.add_device(mdev)

    @staticmethod
    def _guest_add_spice_channel(guest):
        if (
            CONF.spice.enabled and CONF.spice.agent_enabled and
            CONF.libvirt.virt_type != 'lxc'
        ):
            channel = vconfig.LibvirtConfigGuestChannel()
            channel.type = 'spicevmc'
            channel.target_name = "com.redhat.spice.0"
            guest.add_device(channel)

    @staticmethod
    def _guest_add_memory_balloon(guest):
        # Memory balloon device only support 'qemu/kvm' hypervisor
        if (
            CONF.libvirt.virt_type in ('qemu', 'kvm') and
            CONF.libvirt.mem_stats_period_seconds > 0
        ):
            balloon = vconfig.LibvirtConfigMemoryBalloon()
            balloon.model = 'virtio'
            balloon.period = CONF.libvirt.mem_stats_period_seconds
            guest.add_device(balloon)

    @staticmethod
    def _guest_add_watchdog_action(guest, flavor, image_meta):
        # image meta takes precedence over flavor extra specs; disable the
        # watchdog action by default
        watchdog_action = (flavor.extra_specs.get('hw:watchdog_action') or
                           'disabled')
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
        if CONF.libvirt.virt_type in ('qemu', 'kvm'):
            # Get all generic PCI devices (non-SR-IOV).
            for pci_dev in pci_manager.get_instance_pci_devs(instance):
                guest.add_device(self._get_guest_pci_device(pci_dev))
        else:
            # PCI devices is only supported for QEMU/KVM hypervisor
            if pci_manager.get_instance_pci_devs(instance, 'all'):
                raise exception.PciDeviceUnsupportedHypervisor(
                    type=CONF.libvirt.virt_type
                )

    def _guest_add_accel_pci_devices(self, guest, accel_info):
        """Add all accelerator PCI functions from ARQ list."""
        for arq in accel_info:
            dev = vconfig.LibvirtConfigGuestHostdevPCI()
            pci_addr = arq['attach_handle_info']
            dev.domain, dev.bus, dev.slot, dev.function = (
                pci_addr['domain'], pci_addr['bus'],
                pci_addr['device'], pci_addr['function'])
            self._set_managed_mode(dev)

            guest.add_device(dev)

    @staticmethod
    def _guest_add_video_device(guest):
        if CONF.libvirt.virt_type == 'lxc':
            return False

        # NB some versions of libvirt support both SPICE and VNC
        # at the same time. We're not trying to second guess which
        # those versions are. We'll just let libvirt report the
        # errors appropriately if the user enables both.
        add_video_driver = False

        if CONF.vnc.enabled:
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "vnc"
            graphics.listen = CONF.vnc.server_listen
            guest.add_device(graphics)
            add_video_driver = True

        if CONF.spice.enabled:
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "spice"
            graphics.listen = CONF.spice.server_listen
            guest.add_device(graphics)
            add_video_driver = True

        return add_video_driver

    def _get_pointer_bus_and_model(
        self,
        guest: vconfig.LibvirtConfigGuest,
        image_meta: objects.ImageMeta,
    ) -> ty.Tuple[ty.Optional[str], ty.Optional[str]]:
        pointer_bus = image_meta.properties.get('hw_input_bus')
        pointer_model = image_meta.properties.get('hw_pointer_model')

        if pointer_bus:
            pointer_model = 'tablet'
            pointer_bus = pointer_bus
        elif pointer_model or CONF.pointer_model == 'usbtablet':
            # Handle the legacy 'hw_pointer_model' image metadata property
            pointer_model = 'tablet'
            pointer_bus = 'usb'
        else:
            # If the user hasn't requested anything and the host config says to
            # use something other than a USB tablet, there's nothing to do
            return None, None

        # For backward compatibility, we don't want to error out if the host
        # configuration requests a USB tablet but the virtual machine mode is
        # not configured as HVM.
        if guest.os_type != fields.VMMode.HVM:
            LOG.warning(
                'USB tablet requested for guests on non-HVM host; '
                'in order to accept this request the machine mode should '
                'be configured as HVM.')
            return None, None

        # Ditto for using a USB tablet when the SPICE agent is enabled, since
        # that has a paravirt mouse builtin which drastically reduces overhead;
        # this only applies if VNC is not also enabled though, since that still
        # needs the device
        if (
            CONF.spice.enabled and CONF.spice.agent_enabled and
            not CONF.vnc.enabled
        ):
            LOG.warning(
                'USB tablet requested for guests but the SPICE agent is '
                'enabled; ignoring request in favour of default '
                'configuration.')
            return None, None

        return pointer_model, pointer_bus

    def _guest_add_pointer_device(
        self,
        guest: vconfig.LibvirtConfigGuest,
        image_meta: objects.ImageMeta
    ) -> None:
        """Build the pointer device to add to the instance.

        The configuration is determined by examining the 'hw_input_bus' image
        metadata property, the 'hw_pointer_model' image metadata property, and
        the '[DEFAULT] pointer_model' config option in that order.
        """
        pointer_model, pointer_bus = self._get_pointer_bus_and_model(
            guest, image_meta)

        if pointer_model and pointer_bus:
            pointer = vconfig.LibvirtConfigGuestInput()
            pointer.type = pointer_model
            pointer.bus = pointer_bus
            guest.add_device(pointer)

            # returned for unit testing purposes
            return pointer

    def _guest_add_keyboard_device(self, guest, image_meta):
        """Add keyboard for graphical console use."""
        bus = image_meta.properties.get('hw_input_bus')

        if not bus:
            # AArch64 doesn't provide a default keyboard so we explicitly add
            # one; for everything else we rely on default (e.g. for x86,
            # libvirt will automatically add a PS2 keyboard)
            # TODO(stephenfin): We might want to do this for other non-x86
            # architectures
            arch = libvirt_utils.get_arch(image_meta)
            if arch != fields.Architecture.AARCH64:
                return None

            bus = 'usb'

        keyboard = vconfig.LibvirtConfigGuestInput()
        keyboard.type = 'keyboard'
        keyboard.bus = bus
        guest.add_device(keyboard)

        # returned for unit testing purposes
        return keyboard

    def _get_guest_xml(self, context, instance, network_info, disk_info,
                       image_meta, rescue=None,
                       block_device_info=None,
                       mdevs=None, accel_info=None):
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
                                      context, mdevs, accel_info)
        xml = conf.to_xml()

        LOG.debug('End _get_guest_xml xml=%(xml)s',
                  {'xml': xml}, instance=instance)
        return xml

    def get_info(self, instance, use_cache=True):
        """Retrieve information from libvirt for a specific instance.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        :param instance: nova.objects.instance.Instance object
        :param use_cache: unused in this driver
        :returns: An InstanceInfo object
        """
        guest = self._host.get_guest(instance)
        # Kind of ugly but we need to pass host to get_info as for a
        # workaround, see libvirt/compat.py
        return guest.get_info(self._host)

    def _create_domain_setup_lxc(self, context, instance, image_meta,
                                 block_device_info):
        inst_path = libvirt_utils.get_instance_path(instance)
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        root_disk = block_device.get_root_bdm(block_device_mapping)
        if root_disk:
            self._connect_volume(context, root_disk['connection_info'],
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
    def _lxc_disk_handler(self, context, instance, image_meta,
                          block_device_info):
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

        self._create_domain_setup_lxc(context, instance, image_meta,
                                      block_device_info)

        try:
            yield
        finally:
            self._create_domain_cleanup_lxc(instance)

    def _create_guest(
        self,
        context: nova_context.RequestContext,
        xml: str,
        instance: 'objects.Instance',
        power_on: bool = True,
        pause: bool = False,
        post_xml_callback: ty.Callable = None,
    ) -> libvirt_guest.Guest:
        """Create a Guest from XML.

        Create a Guest, which in turn creates a libvirt domain, from XML,
        optionally starting it after creation.

        :returns guest.Guest: Created guest.
        """
        libvirt_secret = None
        # determine whether vTPM is in use and, if so, create the secret
        if CONF.libvirt.swtpm_enabled and hardware.get_vtpm_constraint(
            instance.flavor, instance.image_meta,
        ):
            secret_uuid, passphrase = crypto.ensure_vtpm_secret(
                context, instance)
            libvirt_secret = self._host.create_secret(
                'vtpm', instance.uuid, password=passphrase,
                uuid=secret_uuid)

        try:
            guest = libvirt_guest.Guest.create(xml, self._host)
            if post_xml_callback is not None:
                post_xml_callback()

            if power_on or pause:
                guest.launch(pause=pause)

            return guest
        finally:
            if libvirt_secret is not None:
                libvirt_secret.undefine()

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

    def _create_guest_with_network(
        self,
        context: nova_context.RequestContext,
        xml: str,
        instance: 'objects.Instance',
        network_info: network_model.NetworkInfo,
        block_device_info: ty.Optional[ty.Dict[str, ty.Any]],
        power_on: bool = True,
        vifs_already_plugged: bool = False,
        post_xml_callback: ty.Callable = None,
        external_events: ty.Optional[ty.List[ty.Tuple[str, str]]] = None,
        cleanup_instance_dir: bool = False,
        cleanup_instance_disks: bool = False,
    ) -> libvirt_guest.Guest:
        """Do required network setup and create domain."""

        timeout = CONF.vif_plugging_timeout
        if (
            CONF.libvirt.virt_type in ('kvm', 'qemu') and
            not vifs_already_plugged and power_on and timeout
        ):
            events = (external_events if external_events
                      else self._get_neutron_events(network_info))
        else:
            events = []

        pause = bool(events)
        try:
            with self.virtapi.wait_for_instance_event(
                instance, events, deadline=timeout,
                error_callback=self._neutron_failed_callback,
            ):
                self.plug_vifs(instance, network_info)
                with self._lxc_disk_handler(
                    context, instance, instance.image_meta, block_device_info,
                ):
                    guest = self._create_guest(
                        context, xml, instance,
                        pause=pause, power_on=power_on,
                        post_xml_callback=post_xml_callback)
        except eventlet.timeout.Timeout:
            # We never heard from Neutron
            LOG.warning(
                'Timeout waiting for %(events)s for instance with '
                'vm_state %(vm_state)s and task_state %(task_state)s',
                {
                    'events': events,
                    'vm_state': instance.vm_state,
                    'task_state': instance.task_state,
                },
                instance=instance)

            if CONF.vif_plugging_is_fatal:
                # NOTE(stephenfin): don't worry, guest will be in scope since
                # we can only hit this branch if the VIF plug timed out
                if guest.is_active():
                    guest.poweroff()
                self._cleanup(
                    context, instance, network_info, block_device_info,
                    destroy_vifs=True,
                    cleanup_instance_dir=cleanup_instance_dir,
                    cleanup_instance_disks=cleanup_instance_disks)
                raise exception.VirtualInterfaceCreateException()
        except Exception:
            # Any other error, be sure to clean up
            LOG.error('Failed to start libvirt guest', instance=instance)
            with excutils.save_and_reraise_exception():
                self._cleanup(
                    context, instance, network_info, block_device_info,
                    destroy_vifs=True,
                    cleanup_instance_dir=cleanup_instance_dir,
                    cleanup_instance_disks=cleanup_instance_disks)

        # Resume only if domain has been paused
        if pause:
            guest.resume()

        return guest

    def _get_pcpu_available(self):
        """Get number of host cores to be used for PCPUs.

        :returns: The number of host cores to be used for PCPUs.
        """
        if not CONF.compute.cpu_dedicated_set:
            return set()

        online_cpus = self._host.get_online_cpus()
        dedicated_cpus = hardware.get_cpu_dedicated_set()

        if not dedicated_cpus.issubset(online_cpus):
            msg = _("Invalid '[compute] cpu_dedicated_set' config: one or "
                    "more of the configured CPUs is not online. Online "
                    "cpuset(s): %(online)s, configured cpuset(s): %(req)s")
            raise exception.Invalid(msg % {
                'online': sorted(online_cpus),
                'req': sorted(dedicated_cpus)})

        return dedicated_cpus

    def _get_vcpu_available(self):
        """Get host cores to be used for VCPUs.

        :returns: A list of host CPU cores that can be used for VCPUs.
        """
        online_cpus = self._host.get_online_cpus()

        # NOTE(stephenfin): The use of the legacy 'vcpu_pin_set' option happens
        # if it's defined, regardless of whether '[compute] cpu_shared_set' is
        # also configured. This is legacy behavior required for upgrades that
        # should be removed in the future, when we can rely exclusively on
        # '[compute] cpu_shared_set'.
        if CONF.vcpu_pin_set:
            # TODO(stephenfin): Remove this in U
            shared_cpus = hardware.get_vcpu_pin_set()
        elif CONF.compute.cpu_shared_set:
            shared_cpus = hardware.get_cpu_shared_set()
        elif CONF.compute.cpu_dedicated_set:
            return set()
        else:
            return online_cpus

        if not shared_cpus.issubset(online_cpus):
            msg = _("Invalid '%(config_opt)s' config: one or "
                    "more of the configured CPUs is not online. Online "
                    "cpuset(s): %(online)s, configured cpuset(s): %(req)s")

            if CONF.vcpu_pin_set:
                config_opt = 'vcpu_pin_set'
            else:  # CONF.compute.cpu_shared_set
                config_opt = '[compute] cpu_shared_set'

            raise exception.Invalid(msg % {
                'config_opt': config_opt,
                'online': sorted(online_cpus),
                'req': sorted(shared_cpus)})

        return shared_cpus

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
            info = rbd_utils.RBDDriver().get_pool_info()
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

    def _get_supported_vgpu_types(self):
        if not CONF.devices.enabled_mdev_types:
            return []

        # Make sure we register all the types as the compute service could
        # be calling this method before init_host()
        if len(CONF.devices.enabled_mdev_types) > 1:
            nova.conf.devices.register_dynamic_opts(CONF)

        for vgpu_type in CONF.devices.enabled_mdev_types:
            group = getattr(CONF, 'mdev_%s' % vgpu_type, None)
            if group is None or not group.device_addresses:
                first_type = CONF.devices.enabled_mdev_types[0]
                if len(CONF.devices.enabled_mdev_types) > 1:
                    # Only provide the warning if the operator provided more
                    # than one type as it's not needed to provide groups
                    # if you only use one vGPU type.
                    msg = ("The mdev type '%(type)s' was listed in '[devices] "
                           "enabled_mdev_types' but no corresponding "
                           "'[mdev_%(type)s]' group or "
                           "'[mdev_%(type)s] device_addresses' "
                           "option was defined. Only the first type "
                           "'%(ftype)s' will be used." % {'type': vgpu_type,
                                                         'ftype': first_type})
                    LOG.warning(msg)
                # We need to reset the mapping tables that we started to
                # provide keys and values from previously processed vGPUs but
                # since there is a problem for this vGPU type, we only want to
                # support only the first type.
                self.pgpu_type_mapping.clear()
                self.mdev_class_mapping.clear()
                # Given we only have one type, we default to only support the
                # VGPU resource class.
                self.mdev_classes = {orc.VGPU}
                return [first_type]
            mdev_class = group.mdev_class
            for device_address in group.device_addresses:
                if device_address in self.pgpu_type_mapping:
                    raise exception.InvalidLibvirtMdevConfig(
                        reason="duplicate types for PCI ID %s" % device_address
                    )
                # Just checking whether the operator fat-fingered the address.
                # If it's wrong, it will return an exception
                try:
                    pci_utils.parse_address(device_address)
                except exception.PciDeviceWrongAddressFormat:
                    raise exception.InvalidLibvirtMdevConfig(
                        reason="incorrect PCI address: %s" % device_address
                    )
                self.pgpu_type_mapping[device_address] = vgpu_type
                self.mdev_class_mapping[device_address] = mdev_class
                self.mdev_classes.add(mdev_class)
        return CONF.devices.enabled_mdev_types

    @staticmethod
    def _get_pci_id_from_libvirt_name(
            libvirt_address: str
        ) -> ty.Optional[str]:
        """Returns a PCI ID from a libvirt pci address name.

        :param libvirt_address: the libvirt PCI device name,
                                eg.'pci_0000_84_00_0'
        """
        try:
            device_address = "{}:{}:{}.{}".format(
                *libvirt_address[4:].split('_'))
            # Validates whether it's a PCI ID...
            pci_utils.parse_address(device_address)
        # .format() can return IndexError
        except (exception.PciDeviceWrongAddressFormat, IndexError):
            # this is not a valid PCI address
            LOG.warning("The PCI address %s was invalid for getting the "
                        "related mdev type", libvirt_address)
            return None
        return device_address

    def _get_vgpu_type_per_pgpu(self, device_address):
        """Provides the vGPU type the pGPU supports.

        :param device_address: the libvirt PCI device name,
                               eg.'pci_0000_84_00_0'
        """
        # Bail out quickly if we don't support vGPUs
        if not self.supported_vgpu_types:
            return

        if len(self.supported_vgpu_types) == 1:
            # The operator wanted to only support one single type so we can
            # blindly return it for every single pGPU
            return self.supported_vgpu_types[0]
        device_address = self._get_pci_id_from_libvirt_name(device_address)
        if not device_address:
            return
        try:
            return self.pgpu_type_mapping.get(device_address)
        except KeyError:
            LOG.warning("No mdev type was configured for PCI address: %s",
                        device_address)
            # We accept to return None instead of raising an exception
            # because we prefer the callers to return the existing exceptions
            # in case we can't find a specific pGPU
            return

    def _get_resource_class_for_device(self, device_address):
        """Returns the resource class for the inventory of this device.

        :param device_address: the libvirt PCI device name,
                               eg.'pci_0000_84_00_0'
        """

        device_address = self._get_pci_id_from_libvirt_name(device_address)
        if not device_address:
            # By default, we should always support VGPU as the standard RC
            return orc.VGPU
        # Remember, this is a defaultdict with orc.VGPU as the default RC
        mdev_class = self.mdev_class_mapping[device_address]
        return mdev_class

    def _get_supported_mdev_resource_classes(self):
        return self.mdev_classes

    def _count_mediated_devices(self, enabled_mdev_types):
        """Counts the sysfs objects (handles) that represent a mediated device
        and filtered by $enabled_mdev_types.

        Those handles can be in use by a libvirt guest or not.

        :param enabled_mdev_types: list of enabled VGPU types on this host
        :returns: dict, keyed by parent GPU libvirt PCI device ID, of number of
        mdev device handles for that GPU
        """

        counts_per_parent: ty.Dict[str, int] = collections.defaultdict(int)
        mediated_devices = self._get_mediated_devices(types=enabled_mdev_types)
        for mdev in mediated_devices:
            parent_vgpu_type = self._get_vgpu_type_per_pgpu(mdev['parent'])
            if mdev['type'] != parent_vgpu_type:
                # Even if some mdev was created for another vGPU type, just
                # verify all the mdevs related to the type that their pGPU
                # has
                continue
            counts_per_parent[mdev['parent']] += 1
        return counts_per_parent

    def _count_mdev_capable_devices(self, enabled_mdev_types):
        """Counts the mdev-capable devices on this host filtered by
        $enabled_mdev_types.

        :param enabled_mdev_types: list of enabled VGPU types on this host
        :returns: dict, keyed by device name, to an integer count of available
            instances of each type per device
        """
        mdev_capable_devices = self._get_mdev_capable_devices(
            types=enabled_mdev_types)
        counts_per_dev: ty.Dict[str, int] = collections.defaultdict(int)
        for dev in mdev_capable_devices:
            # dev_id is the libvirt name for the PCI device,
            # eg. pci_0000_84_00_0 which matches a PCI address of 0000:84:00.0
            dev_name = dev['dev_id']
            dev_supported_type = self._get_vgpu_type_per_pgpu(dev_name)
            for _type in dev['types']:
                if _type != dev_supported_type:
                    # This is not the type the operator wanted to support for
                    # this physical GPU
                    continue
                available = dev['types'][_type]['availableInstances']
                # NOTE(sbauza): Even if we support multiple types, Nova will
                # only use one per physical GPU.
                counts_per_dev[dev_name] += available
        return counts_per_dev

    def _get_gpu_inventories(self):
        """Returns the inventories for each physical GPU for a specific type
        supported by the enabled_mdev_types CONF option.

        :returns: dict, keyed by libvirt PCI name, of dicts like:
                {'pci_0000_84_00_0':
                    {'total': $TOTAL,
                     'min_unit': 1,
                     'max_unit': $TOTAL,
                     'step_size': 1,
                     'reserved': 0,
                     'allocation_ratio': 1.0,
                    }
                }
        """

        # Bail out early if operator doesn't care about providing vGPUs
        enabled_mdev_types = self.supported_vgpu_types
        if not enabled_mdev_types:
            return {}
        inventories = {}
        count_per_parent = self._count_mediated_devices(enabled_mdev_types)
        for dev_name, count in count_per_parent.items():
            inventories[dev_name] = {'total': count}
        # Filter how many available mdevs we can create for all the supported
        # types.
        count_per_dev = self._count_mdev_capable_devices(enabled_mdev_types)
        # Combine the counts into the dict that we return to the caller.
        for dev_name, count in count_per_dev.items():
            inv_per_parent = inventories.setdefault(
                dev_name, {'total': 0})
            inv_per_parent['total'] += count
            inv_per_parent.update({
                'min_unit': 1,
                'step_size': 1,
                'reserved': 0,
                # NOTE(sbauza): There is no sense to have a ratio but 1.0
                # since we can't overallocate vGPU resources
                'allocation_ratio': 1.0,
                # FIXME(sbauza): Some vendors could support only one
                'max_unit': inv_per_parent['total'],
            })

        return inventories

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
            for domain_type in g.domains:
                try:
                    instance_cap = (
                        fields.Architecture.canonicalize(g.arch),
                        fields.HVType.canonicalize(domain_type),
                        fields.VMMode.canonicalize(g.ostype))
                    instance_caps.append(instance_cap)
                except exception.InvalidArchitectureName:
                    # NOTE(danms): Libvirt is exposing a guest arch that nova
                    # does not even know about. Avoid aborting here and
                    # continue to process the rest.
                    pass

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

    # TODO(stephenfin): Move this to 'host.py'
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
        dev_flags = (
            libvirt.VIR_CONNECT_LIST_NODE_DEVICES_CAP_NET |
            libvirt.VIR_CONNECT_LIST_NODE_DEVICES_CAP_PCI_DEV
        )
        if self._host.has_min_version(
            lv_ver=MIN_LIBVIRT_VDPA, hv_ver=MIN_QEMU_VDPA,
        ):
            try:
                dev_flags |= libvirt.VIR_CONNECT_LIST_NODE_DEVICES_CAP_VDPA
            except AttributeError:
                pass

        devices = {
            dev.name(): dev for dev in
            self._host.list_all_devices(flags=dev_flags)
        }
        net_devs = [dev for dev in devices.values() if "net" in dev.listCaps()]
        vdpa_devs = [
            dev for dev in devices.values() if "vdpa" in dev.listCaps()
        ]
        pci_info = [
            self._host._get_pcidev_info(name, dev, net_devs, vdpa_devs)
            for name, dev in devices.items() if "pci" in dev.listCaps()
        ]
        return jsonutils.dumps(pci_info)

    def _get_mdev_capabilities_for_dev(self, devname, types=None):
        """Returns a dict of MDEV capable device with the ID as first key
        and then a list of supported types, each of them being a dict.

        :param types: Only return those specific types.
        """
        virtdev = self._host.device_lookup_by_name(devname)
        xmlstr = virtdev.XMLDesc(0)
        cfgdev = vconfig.LibvirtConfigNodeDevice()
        cfgdev.parse_str(xmlstr)

        device = {
            "dev_id": cfgdev.name,
            "types": {},
            "vendor_id": cfgdev.pci_capability.vendor_id,
        }
        for mdev_cap in cfgdev.pci_capability.mdev_capability:
            for cap in mdev_cap.mdev_types:
                if not types or cap['type'] in types:
                    device["types"].update({cap['type']: {
                        'availableInstances': cap['availableInstances'],
                        # This attribute is optional
                        'name': cap.get('name'),
                        'deviceAPI': cap['deviceAPI']}})
        return device

    def _get_mdev_capable_devices(self, types=None):
        """Get host devices supporting mdev types.

        Obtain devices information from libvirt and returns a list of
        dictionaries.

        :param types: Filter only devices supporting those types.
        """
        dev_names = self._host.list_mdev_capable_devices() or []
        mdev_capable_devices = []
        for name in dev_names:
            device = self._get_mdev_capabilities_for_dev(name, types)
            if not device["types"]:
                continue
            mdev_capable_devices.append(device)
        return mdev_capable_devices

    def _get_mediated_device_information(self, devname):
        """Returns a dict of a mediated device."""
        virtdev = self._host.device_lookup_by_name(devname)
        xmlstr = virtdev.XMLDesc(0)
        cfgdev = vconfig.LibvirtConfigNodeDevice()
        cfgdev.parse_str(xmlstr)

        device = {
            "dev_id": cfgdev.name,
            # name is like mdev_00ead764_fdc0_46b6_8db9_2963f5c815b4
            "uuid": libvirt_utils.mdev_name2uuid(cfgdev.name),
            # the physical GPU PCI device
            "parent": cfgdev.parent,
            "type": cfgdev.mdev_information.type,
            "iommu_group": cfgdev.mdev_information.iommu_group,
        }
        return device

    def _get_mediated_devices(self, types=None):
        """Get host mediated devices.

        Obtain devices information from libvirt and returns a list of
        dictionaries.

        :param types: Filter only devices supporting those types.
        """
        dev_names = self._host.list_mediated_devices() or []
        mediated_devices = []
        for name in dev_names:
            device = self._get_mediated_device_information(name)
            if not types or device["type"] in types:
                mediated_devices.append(device)
        return mediated_devices

    def _get_all_assigned_mediated_devices(self, instance=None):
        """Lookup all instances from the host and return all the mediated
        devices that are assigned to a guest.

        :param instance: Only return mediated devices for that instance.

        :returns: A dictionary of keys being mediated device UUIDs and their
                  respective values the instance UUID of the guest using it.
                  Returns an empty dict if an instance is provided but not
                  found in the hypervisor.
        """
        allocated_mdevs = {}
        if instance:
            # NOTE(sbauza): In some cases (like a migration issue), the
            # instance can exist in the Nova database but libvirt doesn't know
            # about it. For such cases, the way to fix that is to hard reboot
            # the instance, which will recreate the libvirt guest.
            # For that reason, we need to support that case by making sure
            # we don't raise an exception if the libvirt guest doesn't exist.
            try:
                guest = self._host.get_guest(instance)
            except exception.InstanceNotFound:
                # Bail out early if libvirt doesn't know about it since we
                # can't know the existing mediated devices
                return {}
            guests = [guest]
        else:
            guests = self._host.list_guests(only_running=False)
        for guest in guests:
            cfg = guest.get_config()
            for device in cfg.devices:
                if isinstance(device, vconfig.LibvirtConfigGuestHostdevMDEV):
                    allocated_mdevs[device.uuid] = guest.uuid
        return allocated_mdevs

    # TODO(sbauza): Rename this method into _mdev_allocations
    def _vgpu_allocations(self, allocations):
        """Filtering only the mdev allocations from a list of allocations.

        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
        """
        if not allocations:
            # If no allocations, there is no vGPU request.
            return {}
        mdev_rcs = self._get_supported_mdev_resource_classes()
        vgpu_allocations = {}
        for rp in allocations:
            res = allocations[rp]['resources']
            mdev_resources = {mdev_RC: res[mdev_RC] for mdev_RC in mdev_rcs
                              if mdev_RC in res and res[mdev_RC] > 0}
            if mdev_resources:
                vgpu_allocations[rp] = {'resources': mdev_resources}
        return vgpu_allocations

    def _get_existing_mdevs_not_assigned(self, parent, requested_types=None):
        """Returns the already created mediated devices that are not assigned
        to a guest yet.

        :param parent: Filter out result for only mdevs from the parent device.
        :param requested_types: Filter out the result for only mediated devices
                                having those types.
        """
        allocated_mdevs = self._get_all_assigned_mediated_devices()
        mdevs = self._get_mediated_devices(requested_types)
        available_mdevs = set()
        for mdev in mdevs:
            parent_vgpu_type = self._get_vgpu_type_per_pgpu(mdev['parent'])
            if mdev['type'] != parent_vgpu_type:
                # This mdev is using a vGPU type that is not supported by the
                # configuration option for its pGPU parent, so we can't use it.
                continue
            # FIXME(sbauza): No longer accept the parent value to be nullable
            # once we fix the reshape functional test
            if parent is None or mdev['parent'] == parent:
                available_mdevs.add(mdev["uuid"])

        available_mdevs -= set(allocated_mdevs)
        return available_mdevs

    def _create_new_mediated_device(self, parent, uuid=None):
        """Find a physical device that can support a new mediated device and
        create it.

        :param parent: The libvirt name of the parent GPU, eg. pci_0000_06_00_0
        :param uuid: The possible mdev UUID we want to create again

        :returns: the newly created mdev UUID or None if not possible
        """
        supported_types = self.supported_vgpu_types
        # Try to see if we can still create a new mediated device
        devices = self._get_mdev_capable_devices(supported_types)
        for device in devices:
            dev_name = device['dev_id']
            # FIXME(sbauza): No longer accept the parent value to be nullable
            # once we fix the reshape functional test
            if parent is not None and dev_name != parent:
                # The device is not the one that was called, not creating
                # the mdev
                continue
            dev_supported_type = self._get_vgpu_type_per_pgpu(dev_name)
            if dev_supported_type and device['types'][
                    dev_supported_type]['availableInstances'] > 0:
                # That physical GPU has enough room for a new mdev
                # We need the PCI address, not the libvirt name
                # The libvirt name is like 'pci_0000_84_00_0'
                pci_addr = "{}:{}:{}.{}".format(*dev_name[4:].split('_'))
                chosen_mdev = nova.privsep.libvirt.create_mdev(
                    pci_addr, dev_supported_type, uuid=uuid)
                return chosen_mdev

    @utils.synchronized(VGPU_RESOURCE_SEMAPHORE)
    def _allocate_mdevs(self, allocations):
        """Returns a list of mediated device UUIDs corresponding to available
        resources we can assign to the guest(s) corresponding to the allocation
        requests passed as argument.

        That method can either find an existing but unassigned mediated device
        it can allocate, or create a new mediated device from a capable
        physical device if the latter has enough left capacity.

        :param allocations: Information about resources allocated to the
                            instance via placement, of the form returned by
                            SchedulerReportClient.get_allocations_for_consumer.
                            That code is supporting Placement API version 1.12
        """
        vgpu_allocations = self._vgpu_allocations(allocations)
        if not vgpu_allocations:
            return
        # TODO(sbauza): For the moment, we only support allocations for only
        # one pGPU.
        if len(vgpu_allocations) > 1:
            LOG.warning('More than one allocation was passed over to libvirt '
                        'while at the moment libvirt only supports one. Only '
                        'the first allocation will be looked up.')
        rp_uuid, alloc = next(iter(vgpu_allocations.items()))
        # We only have one allocation with a supported resource class
        vgpus_asked = list(alloc['resources'].values())[0]

        # Find if we allocated against a specific pGPU (and then the allocation
        # is made against a child RP) or any pGPU (in case the VGPU inventory
        # is still on the root RP)
        try:
            allocated_rp = self.provider_tree.data(rp_uuid)
        except ValueError:
            # The provider doesn't exist, return a better understandable
            # exception
            raise exception.ComputeResourcesUnavailable(
                reason='mdev-capable resource is not available')
        # FIXME(sbauza): The functional reshape test assumes that we could
        # run _allocate_mdevs() against non-nested RPs but this is impossible
        # as all inventories have been reshaped *before now* since it's done
        # on init_host() (when the compute restarts or whatever else calls it).
        # That said, since fixing the functional test isn't easy yet, let's
        # assume we still support a non-nested RP for now.
        if allocated_rp.parent_uuid is None:
            # We are on a root RP
            parent_device = None
        else:
            rp_name = allocated_rp.name
            # There can be multiple roots, we need to find the root name
            # to guess the physical device name
            roots = list(self.provider_tree.roots)
            for root in roots:
                if rp_name.startswith(root.name + '_'):
                    # The RP name convention is :
                    #    root_name + '_' + parent_device
                    parent_device = rp_name[len(root.name) + 1:]
                    break
            else:
                LOG.warning(
                    "mdev-capable device name %(name)s can't be guessed from "
                    "the ProviderTree roots %(roots)s",
                    {'name': rp_name,
                     'roots': ', '.join([root.name for root in roots])})
                # We f... have no idea what was the parent device
                # If we can't find devices having available VGPUs, just raise
                raise exception.ComputeResourcesUnavailable(
                    reason='mdev-capable resource is not available')

        supported_types = self.supported_vgpu_types
        # Which mediated devices are created but not assigned to a guest ?
        mdevs_available = self._get_existing_mdevs_not_assigned(
            parent_device, supported_types)

        chosen_mdevs = []
        for c in range(vgpus_asked):
            chosen_mdev = None
            if mdevs_available:
                # Take the first available mdev
                chosen_mdev = mdevs_available.pop()
            else:
                chosen_mdev = self._create_new_mediated_device(parent_device)
            if not chosen_mdev:
                # If we can't find devices having available VGPUs, just raise
                raise exception.ComputeResourcesUnavailable(
                    reason='mdev-capable resource is not available')
            else:
                chosen_mdevs.append(chosen_mdev)
        return chosen_mdevs

    def _detach_mediated_devices(self, guest):
        mdevs = guest.get_all_devices(
            devtype=vconfig.LibvirtConfigGuestHostdevMDEV)
        for mdev_cfg in mdevs:
            try:
                guest.detach_device(mdev_cfg, live=True)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_CONFIG_UNSUPPORTED:
                    reason = _("Suspend is not supported for instances having "
                               "attached mediated devices.")
                    raise exception.InstanceFaultRollback(
                        exception.InstanceSuspendFailure(reason=reason))
                else:
                    raise

    def _attach_mediated_devices(self, guest, devs):
        for mdev_cfg in devs:
            try:
                guest.attach_device(mdev_cfg, live=True)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_DEVICE_MISSING:
                    LOG.warning("The mediated device %s was not found and "
                                "won't be reattached to %s.", mdev_cfg, guest)
                else:
                    raise

    def _get_mdevs_from_guest_config(self, xml):
        """Get all libvirt's mediated devices from a guest's config (XML) file.
        We don't have to worry about those devices being used by another guest,
        since they remain allocated for the current guest as long as they are
        present in the XML.

        :param xml: The XML from the guest we want to get a list of mdevs from.

        :returns: A list containing the objects that represent the mediated
                  devices attached to the guest's config passed as argument.
        """
        config = vconfig.LibvirtConfigGuest()
        config.parse_str(xml)

        devs = []
        for dev in config.devices:
            if isinstance(dev, vconfig.LibvirtConfigGuestHostdevMDEV):
                devs.append(dev)
        return devs

    def _has_numa_support(self):
        # This means that the host can support LibvirtConfigGuestNUMATune
        # and the nodeset field in LibvirtConfigGuestMemoryBackingPage
        caps = self._host.get_capabilities()

        if (caps.host.cpu.arch in (fields.Architecture.I686,
                                   fields.Architecture.X86_64,
                                   fields.Architecture.AARCH64) and
                self._host.has_min_version(hv_type=host.HV_DRIVER_QEMU)):
            return True
        elif (caps.host.cpu.arch in (fields.Architecture.PPC64,
                                     fields.Architecture.PPC64LE)):
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

        available_shared_cpus = self._get_vcpu_available()
        available_dedicated_cpus = self._get_pcpu_available()

        # NOTE(stephenfin): In an ideal world, if the operator had not
        # configured this host to report PCPUs using the '[compute]
        # cpu_dedicated_set' option, then we should not be able to used pinned
        # instances on this host. However, that would force operators to update
        # their configuration as part of the Stein -> Train upgrade or be
        # unable to schedule instances on the host. As a result, we need to
        # revert to legacy behavior and use 'vcpu_pin_set' for both VCPUs and
        # PCPUs.
        # TODO(stephenfin): Remove this in U
        if not available_dedicated_cpus and not (
                CONF.compute.cpu_shared_set and not CONF.vcpu_pin_set):
            available_dedicated_cpus = available_shared_cpus

        def _get_reserved_memory_for_cell(self, cell_id, page_size):
            cell = self._reserved_hugepages.get(cell_id, {})
            return cell.get(page_size, 0)

        def _get_physnet_numa_affinity():
            affinities: ty.Dict[int, ty.Set[str]] = {
                cell.id: set() for cell in topology.cells
            }
            for physnet in CONF.neutron.physnets:
                # This will error out if the group is not registered, which is
                # exactly what we want as that would be a bug
                group = getattr(CONF, 'neutron_physnet_%s' % physnet)

                if not group.numa_nodes:
                    msg = ("the physnet '%s' was listed in '[neutron] "
                           "physnets' but no corresponding "
                           "'[neutron_physnet_%s] numa_nodes' option was "
                           "defined." % (physnet, physnet))
                    raise exception.InvalidNetworkNUMAAffinity(reason=msg)

                for node in group.numa_nodes:
                    if node not in affinities:
                        msg = ("node %d for physnet %s is not present in host "
                               "affinity set %r" % (node, physnet, affinities))
                        # The config option referenced an invalid node
                        raise exception.InvalidNetworkNUMAAffinity(reason=msg)
                    affinities[node].add(physnet)

            return affinities

        def _get_tunnel_numa_affinity():
            affinities = {cell.id: False for cell in topology.cells}

            for node in CONF.neutron_tunnel.numa_nodes:
                if node not in affinities:
                    msg = ("node %d for tunneled networks is not present "
                           "in host affinity set %r" % (node, affinities))
                    # The config option referenced an invalid node
                    raise exception.InvalidNetworkNUMAAffinity(reason=msg)
                affinities[node] = True

            return affinities

        physnet_affinities = _get_physnet_numa_affinity()
        tunnel_affinities = _get_tunnel_numa_affinity()

        for cell in topology.cells:
            cpus = set(cpu.id for cpu in cell.cpus)

            # NOTE(artom) We assume we'll never see hardware with multipe
            # sockets in a single NUMA node - IOW, the socket_id for all CPUs
            # in a single cell will be the same. To make that assumption
            # explicit, we leave the cell's socket_id as None if that's the
            # case.
            socket_id = None
            sockets = set([cpu.socket_id for cpu in cell.cpus])
            if len(sockets) == 1:
                socket_id = sockets.pop()
            else:
                LOG.warning('This host appears to have multiple sockets per '
                            'NUMA node. The `socket` PCI NUMA affinity '
                            'will not be supported.')

            cpuset = cpus & available_shared_cpus
            pcpuset = cpus & available_dedicated_cpus

            # de-duplicate and sort the list of CPU sibling sets
            siblings = sorted(
                set(x) for x in set(
                    tuple(cpu.siblings) or () for cpu in cell.cpus
                )
            )

            cpus &= available_shared_cpus | available_dedicated_cpus
            siblings = [sib & cpus for sib in siblings]
            # Filter out empty sibling sets that may be left
            siblings = [sib for sib in siblings if len(sib) > 0]

            mempages = [
                objects.NUMAPagesTopology(
                    size_kb=pages.size,
                    total=pages.total,
                    used=0,
                    reserved=_get_reserved_memory_for_cell(
                        self, cell.id, pages.size))
                for pages in cell.mempages]

            network_metadata = objects.NetworkMetadata(
                physnets=physnet_affinities[cell.id],
                tunneled=tunnel_affinities[cell.id])

            # NOTE(stephenfin): Note that we don't actually return any usage
            # information here. This is because this is handled by the resource
            # tracker via the 'update_available_resource' periodic task, which
            # loops through all instances and calculated usage accordingly
            cell = objects.NUMACell(
                id=cell.id,
                socket=socket_id,
                cpuset=cpuset,
                pcpuset=pcpuset,
                memory=cell.memory / units.Ki,
                cpu_usage=0,
                pinned_cpus=set(),
                memory_usage=0,
                siblings=siblings,
                mempages=mempages,
                network_metadata=network_metadata)
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
            dev = guest.get_block_device(disk_id)
            return dev.blockStats()
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

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        """Update a ProviderTree object with current resource provider,
        inventory information and CPU traits.

        :param nova.compute.provider_tree.ProviderTree provider_tree:
            A nova.compute.provider_tree.ProviderTree object representing all
            the providers in the tree associated with the compute node, and any
            sharing providers (those with the ``MISC_SHARES_VIA_AGGREGATE``
            trait) associated via aggregate with any of those providers (but
            not *their* tree- or aggregate-associated providers), as currently
            known by placement.
        :param nodename:
            String name of the compute node (i.e.
            ComputeNode.hypervisor_hostname) for which the caller is requesting
            updated provider information.
        :param allocations:
            Dict of allocation data of the form:
              { $CONSUMER_UUID: {
                    # The shape of each "allocations" dict below is identical
                    # to the return from GET /allocations/{consumer_uuid}
                    "allocations": {
                        $RP_UUID: {
                            "generation": $RP_GEN,
                            "resources": {
                                $RESOURCE_CLASS: $AMOUNT,
                                ...
                            },
                        },
                        ...
                    },
                    "project_id": $PROJ_ID,
                    "user_id": $USER_ID,
                    "consumer_generation": $CONSUMER_GEN,
                },
                ...
              }
            If None, and the method determines that any inventory needs to be
            moved (from one provider to another and/or to a different resource
            class), the ReshapeNeeded exception must be raised. Otherwise, this
            dict must be edited in place to indicate the desired final state of
            allocations.
        :raises ReshapeNeeded: If allocations is None and any inventory needs
            to be moved from one provider to another and/or to a different
            resource class.
        :raises: ReshapeFailed if the requested tree reshape fails for
            whatever reason.
        """
        disk_gb = int(self._get_local_gb_info()['total'])
        memory_mb = int(self._host.get_memory_mb_total())
        vcpus = len(self._get_vcpu_available())
        pcpus = len(self._get_pcpu_available())
        memory_enc_slots = self._get_memory_encrypted_slots()

        # NOTE(yikun): If the inv record does not exists, the allocation_ratio
        # will use the CONF.xxx_allocation_ratio value if xxx_allocation_ratio
        # is set, and fallback to use the initial_xxx_allocation_ratio
        # otherwise.
        inv = provider_tree.data(nodename).inventory
        ratios = self._get_allocation_ratios(inv)
        resources: ty.Dict[str, ty.Set['objects.Resource']] = (
            collections.defaultdict(set)
        )

        result = {}
        if memory_mb:
            result[orc.MEMORY_MB] = {
                'total': memory_mb,
                'min_unit': 1,
                'max_unit': memory_mb,
                'step_size': 1,
                'allocation_ratio': ratios[orc.MEMORY_MB],
                'reserved': CONF.reserved_host_memory_mb,
            }

        # NOTE(stephenfin): We have to optionally report these since placement
        # forbids reporting inventory with total=0
        if vcpus:
            result[orc.VCPU] = {
                'total': vcpus,
                'min_unit': 1,
                'max_unit': vcpus,
                'step_size': 1,
                'allocation_ratio': ratios[orc.VCPU],
                'reserved': CONF.reserved_host_cpus,
            }

        if pcpus:
            result[orc.PCPU] = {
                'total': pcpus,
                'min_unit': 1,
                'max_unit': pcpus,
                'step_size': 1,
                'allocation_ratio': 1,
                'reserved': 0,
            }

        if memory_enc_slots:
            result[orc.MEM_ENCRYPTION_CONTEXT] = {
                'total': memory_enc_slots,
                'min_unit': 1,
                'max_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
                'reserved': 0,
            }

        # If a sharing DISK_GB provider exists in the provider tree, then our
        # storage is shared, and we should not report the DISK_GB inventory in
        # the compute node provider.
        # TODO(efried): Reinstate non-reporting of shared resource by the
        # compute RP once the issues from bug #1784020 have been resolved.
        if provider_tree.has_sharing_provider(orc.DISK_GB):
            LOG.debug('Ignoring sharing provider - see bug #1784020')

        if disk_gb:
            result[orc.DISK_GB] = {
                'total': disk_gb,
                'min_unit': 1,
                'max_unit': disk_gb,
                'step_size': 1,
                'allocation_ratio': ratios[orc.DISK_GB],
                'reserved': (self._get_reserved_host_disk_gb_from_config() +
                             self._get_disk_size_reserved_for_image_cache()),
            }

        # TODO(sbauza): Use traits to providing vGPU types. For the moment,
        # it will be only documentation support by explaining to use
        # osc-placement to create custom traits for each of the pGPU RPs.
        self._update_provider_tree_for_vgpu(
           provider_tree, nodename, allocations=allocations)

        self._update_provider_tree_for_pcpu(
            provider_tree, nodename, allocations=allocations)

        self._update_provider_tree_for_vpmems(
            provider_tree, nodename, result, resources)

        provider_tree.update_inventory(nodename, result)
        provider_tree.update_resources(nodename, resources)

        # Add supported traits i.e. those equal to True to provider tree while
        # removing the unsupported ones
        traits_to_add = [
            t for t in self.static_traits if self.static_traits[t]
        ]
        traits_to_remove = set(self.static_traits) - set(traits_to_add)
        provider_tree.add_traits(nodename, *traits_to_add)
        provider_tree.remove_traits(nodename, *traits_to_remove)

        # Now that we updated the ProviderTree, we want to store it locally
        # so that spawn() or other methods can access it thru a getter
        self.provider_tree = copy.deepcopy(provider_tree)

    def _update_provider_tree_for_vpmems(self, provider_tree, nodename,
                                         inventory, resources):
        """Update resources and inventory for vpmems in provider tree."""
        prov_data = provider_tree.data(nodename)
        for rc, vpmems in self._vpmems_by_rc.items():
            # Skip (and omit) inventories with total=0 because placement does
            # not allow setting total=0 for inventory.
            if not len(vpmems):
                continue
            inventory[rc] = {
                'total': len(vpmems),
                'max_unit': len(vpmems),
                'min_unit': 1,
                'step_size': 1,
                'allocation_ratio': 1.0,
                'reserved': 0
            }
            for vpmem in vpmems:
                resource_obj = objects.Resource(
                    provider_uuid=prov_data.uuid,
                    resource_class=rc,
                    identifier=vpmem.name,
                    metadata=vpmem)
                resources[rc].add(resource_obj)

    def _get_memory_encrypted_slots(self):
        slots = CONF.libvirt.num_memory_encrypted_guests
        if not self._host.supports_amd_sev:
            if slots and slots > 0:
                LOG.warning("Host is configured with "
                            "libvirt.num_memory_encrypted_guests set to "
                            "%d, but is not SEV-capable.", slots)
            return 0

        # NOTE(aspiers): Auto-detection of the number of available
        # slots for AMD SEV is not yet possible, so honor the
        # configured value, or impose no limit if this is not
        # specified.  This does incur a risk that if operators don't
        # read the instructions and configure the maximum correctly,
        # the maximum could be exceeded resulting in SEV guests
        # failing at launch-time.  However at least SEV guests will
        # launch until the maximum, and when auto-detection code is
        # added later, an upgrade will magically fix the issue.
        #
        # Note also that the configured value can be 0 on an
        # SEV-capable host, since there might conceivably be good
        # reasons for the operator to want to disable SEV even when
        # it's available (e.g. due to performance impact, or
        # implementation bugs which may surface later).
        if slots is not None:
            return slots
        else:
            return db_const.MAX_INT

    @property
    def static_traits(self) -> ty.Dict[str, bool]:
        if self._static_traits is not None:
            return self._static_traits

        traits: ty.Dict[str, bool] = {}
        traits.update(self._get_cpu_traits())
        traits.update(self._get_storage_bus_traits())
        traits.update(self._get_video_model_traits())
        traits.update(self._get_vif_model_traits())
        traits.update(self._get_tpm_traits())

        _, invalid_traits = ot.check_traits(traits)
        for invalid_trait in invalid_traits:
            LOG.debug("Trait '%s' is not valid; ignoring.", invalid_trait)
            del traits[invalid_trait]

        self._static_traits = traits

        return self._static_traits

    @staticmethod
    def _is_reshape_needed_vgpu_on_root(provider_tree, nodename):
        """Determine if root RP has VGPU inventories.

        Check to see if the root compute node provider in the tree for
        this host already has VGPU inventory because if it does, we either
        need to signal for a reshape (if _update_provider_tree_for_vgpu()
        has no allocations) or move the allocations within the ProviderTree if
        passed.

        :param provider_tree: The ProviderTree object for this host.
        :param nodename: The ComputeNode.hypervisor_hostname, also known as
            the name of the root node provider in the tree for this host.
        :returns: boolean, whether we have VGPU root inventory.
        """
        root_node = provider_tree.data(nodename)
        return orc.VGPU in root_node.inventory

    def _ensure_pgpu_providers(self, inventories_dict, provider_tree,
                               nodename):
        """Ensures GPU inventory providers exist in the tree for $nodename.

        GPU providers are named $nodename_$gpu-device-id, e.g.
        ``somehost.foo.bar.com_pci_0000_84_00_0``.

        :param inventories_dict: Dictionary of inventories for VGPU class
            directly provided by _get_gpu_inventories() and which looks like:
                {'pci_0000_84_00_0':
                    {'total': $TOTAL,
                     'min_unit': 1,
                     'max_unit': $MAX_UNIT, # defaults to $TOTAL
                     'step_size': 1,
                     'reserved': 0,
                     'allocation_ratio': 1.0,
                    }
                }
        :param provider_tree: The ProviderTree to update.
        :param nodename: The ComputeNode.hypervisor_hostname, also known as
            the name of the root node provider in the tree for this host.
        :returns: dict, keyed by GPU device ID, to ProviderData object
            representing that resource provider in the tree
        """
        # Create the VGPU child providers if they do not already exist.
        # Dict of PGPU RPs keyed by their libvirt PCI name
        pgpu_rps = {}
        for pgpu_dev_id, inventory in inventories_dict.items():
            # Skip (and omit) inventories with total=0 because placement does
            # not allow setting total=0 for inventory.
            if not inventory['total']:
                continue
            # For each physical GPU, we make sure to have a child provider
            pgpu_rp_name = '%s_%s' % (nodename, pgpu_dev_id)
            if not provider_tree.exists(pgpu_rp_name):
                # This is the first time creating the child provider so add
                # it to the tree under the root node provider.
                provider_tree.new_child(pgpu_rp_name, nodename)
            # We want to idempotently return the resource providers with VGPUs
            pgpu_rp = provider_tree.data(pgpu_rp_name)
            pgpu_rps[pgpu_dev_id] = pgpu_rp

            # The VGPU inventory goes on a child provider of the given root
            # node, identified by $nodename.
            mdev_rc = self._get_resource_class_for_device(pgpu_dev_id)
            pgpu_inventory = {mdev_rc: inventory}
            provider_tree.update_inventory(pgpu_rp_name, pgpu_inventory)
        return pgpu_rps

    @staticmethod
    def _assert_is_root_provider(
            rp_uuid, root_node, consumer_uuid, alloc_data):
        """Asserts during a reshape that rp_uuid is for the root node provider.

        When reshaping, inventory and allocations should be on the root node
        provider and then moved to child providers.

        :param rp_uuid: UUID of the provider that holds inventory/allocations.
        :param root_node: ProviderData object representing the root node in a
            provider tree.
        :param consumer_uuid: UUID of the consumer (instance) holding resource
            allocations against the given rp_uuid provider.
        :param alloc_data: dict of allocation data for the consumer.
        :raises: ReshapeFailed if rp_uuid is not the root node indicating a
            reshape was needed but the inventory/allocation structure is not
            expected.
        """
        if rp_uuid != root_node.uuid:
            # Something is wrong - VGPU inventory should
            # only be on the root node provider if we are
            # reshaping the tree.
            msg = (_('Unexpected VGPU resource allocation '
                     'on provider %(rp_uuid)s for consumer '
                     '%(consumer_uuid)s: %(alloc_data)s. '
                     'Expected VGPU allocation to be on root '
                     'compute node provider %(root_uuid)s.')
                   % {'rp_uuid': rp_uuid,
                      'consumer_uuid': consumer_uuid,
                      'alloc_data': alloc_data,
                      'root_uuid': root_node.uuid})
            raise exception.ReshapeFailed(error=msg)

    def _get_assigned_mdevs_for_reshape(
            self, instance_uuid, rp_uuid, alloc_data):
        """Gets the mediated devices assigned to the instance during a reshape.

        :param instance_uuid: UUID of the instance consuming VGPU resources
            on this host.
        :param rp_uuid: UUID of the resource provider with VGPU inventory being
            consumed by the instance.
        :param alloc_data: dict of allocation data for the instance consumer.
        :return: list of mediated device UUIDs assigned to the instance
        :raises: ReshapeFailed if the instance is not found in the hypervisor
            or no mediated devices were found to be assigned to the instance
            indicating VGPU allocations are out of sync with the hypervisor
        """
        # FIXME(sbauza): We don't really need an Instance
        # object, but given some libvirt.host logs needs
        # to have an instance name, just provide a fake one
        Instance = collections.namedtuple('Instance', ['uuid', 'name'])
        instance = Instance(uuid=instance_uuid, name=instance_uuid)
        mdevs = self._get_all_assigned_mediated_devices(instance)
        # _get_all_assigned_mediated_devices returns {} if the instance is
        # not found in the hypervisor
        if not mdevs:
            # If we found a VGPU allocation against a consumer
            # which is not an instance, the only left case for
            # Nova would be a migration but we don't support
            # this at the moment.
            msg = (_('Unexpected VGPU resource allocation on provider '
                     '%(rp_uuid)s for consumer %(consumer_uuid)s: '
                     '%(alloc_data)s. The allocation is made against a '
                     'non-existing instance or there are no devices assigned.')
                   % {'rp_uuid': rp_uuid, 'consumer_uuid': instance_uuid,
                      'alloc_data': alloc_data})
            raise exception.ReshapeFailed(error=msg)
        return mdevs

    def _count_vgpus_per_pgpu(self, mdev_uuids):
        """Count the number of VGPUs per physical GPU mediated device.

        :param mdev_uuids: List of physical GPU mediated device UUIDs.
        :return: dict, keyed by PGPU device ID, to count of VGPUs on that
            device
        """
        vgpu_count_per_pgpu: ty.Dict[str, int] = collections.defaultdict(int)
        for mdev_uuid in mdev_uuids:
            # libvirt name is like mdev_00ead764_fdc0_46b6_8db9_2963f5c815b4
            dev_name = libvirt_utils.mdev_uuid2name(mdev_uuid)
            # Count how many vGPUs are in use for this instance
            dev_info = self._get_mediated_device_information(dev_name)
            pgpu_dev_id = dev_info['parent']
            vgpu_count_per_pgpu[pgpu_dev_id] += 1
        return vgpu_count_per_pgpu

    @staticmethod
    def _check_vgpu_allocations_match_real_use(
            vgpu_count_per_pgpu, expected_usage, rp_uuid, consumer_uuid,
            alloc_data):
        """Checks that the number of GPU devices assigned to the consumer
        matches what is expected from the allocations in the placement service
        and logs a warning if there is a mismatch.

        :param vgpu_count_per_pgpu: dict, keyed by PGPU device ID, to count of
            VGPUs on that device where each device is assigned to the consumer
            (guest instance on this hypervisor)
        :param expected_usage: The expected usage from placement for the
            given resource provider and consumer
        :param rp_uuid: UUID of the resource provider with VGPU inventory being
            consumed by the instance
        :param consumer_uuid: UUID of the consumer (instance) holding resource
            allocations against the given rp_uuid provider
        :param alloc_data: dict of allocation data for the instance consumer
        """
        actual_usage = sum(vgpu_count_per_pgpu.values())
        if actual_usage != expected_usage:
            # Don't make it blocking, just make sure you actually correctly
            # allocate the existing resources
            LOG.warning(
                'Unexpected VGPU resource allocation on provider %(rp_uuid)s '
                'for consumer %(consumer_uuid)s: %(alloc_data)s. Allocations '
                '(%(expected_usage)s) differ from actual use '
                '(%(actual_usage)s).',
                {'rp_uuid': rp_uuid, 'consumer_uuid': consumer_uuid,
                 'alloc_data': alloc_data, 'expected_usage': expected_usage,
                 'actual_usage': actual_usage})

    def _reshape_vgpu_allocations(
            self, rp_uuid, root_node, consumer_uuid, alloc_data, resources,
            pgpu_rps):
        """Update existing VGPU allocations by moving them from the root node
        provider to the child provider for the given VGPU provider.

        :param rp_uuid: UUID of the VGPU resource provider with allocations
            from consumer_uuid (should be the root node provider before
            reshaping occurs)
        :param root_node: ProviderData object for the root compute node
            resource provider in the provider tree
        :param consumer_uuid: UUID of the consumer (instance) with VGPU
            allocations against the resource provider represented by rp_uuid
        :param alloc_data: dict of allocation information for consumer_uuid
        :param resources: dict, keyed by resource class, of resources allocated
            to consumer_uuid from rp_uuid
        :param pgpu_rps: dict, keyed by GPU device ID, to ProviderData object
            representing that resource provider in the tree
        :raises: ReshapeFailed if the reshape fails for whatever reason
        """
        # We've found VGPU allocations on a provider. It should be the root
        # node provider.
        self._assert_is_root_provider(
            rp_uuid, root_node, consumer_uuid, alloc_data)

        # Find which physical GPU corresponds to this allocation.
        mdev_uuids = self._get_assigned_mdevs_for_reshape(
            consumer_uuid, rp_uuid, alloc_data)

        vgpu_count_per_pgpu = self._count_vgpus_per_pgpu(mdev_uuids)

        # We need to make sure we found all the mediated devices that
        # correspond to an allocation.
        self._check_vgpu_allocations_match_real_use(
            vgpu_count_per_pgpu, resources[orc.VGPU],
            rp_uuid, consumer_uuid, alloc_data)

        # Add the VGPU allocation for each VGPU provider.
        allocs = alloc_data['allocations']
        for pgpu_dev_id, pgpu_rp in pgpu_rps.items():
            vgpu_count = vgpu_count_per_pgpu[pgpu_dev_id]
            if vgpu_count:
                allocs[pgpu_rp.uuid] = {
                    'resources': {
                        orc.VGPU: vgpu_count
                    }
                }
        # And remove the VGPU allocation from the root node provider.
        del resources[orc.VGPU]

    def _reshape_gpu_resources(
            self, allocations, root_node, pgpu_rps):
        """Reshapes the provider tree moving VGPU inventory from root to child

        :param allocations:
            Dict of allocation data of the form:
              { $CONSUMER_UUID: {
                    # The shape of each "allocations" dict below is identical
                    # to the return from GET /allocations/{consumer_uuid}
                    "allocations": {
                        $RP_UUID: {
                            "generation": $RP_GEN,
                            "resources": {
                                $RESOURCE_CLASS: $AMOUNT,
                                ...
                            },
                        },
                        ...
                    },
                    "project_id": $PROJ_ID,
                    "user_id": $USER_ID,
                    "consumer_generation": $CONSUMER_GEN,
                },
                ...
              }
        :params root_node: The root node in the provider tree
        :params pgpu_rps: dict, keyed by GPU device ID, to ProviderData object
            representing that resource provider in the tree
        """
        LOG.info('Reshaping tree; moving VGPU allocations from root '
                 'provider %s to child providers %s.', root_node.uuid,
                 pgpu_rps.values())
        # For each consumer in the allocations dict, look for VGPU
        # allocations and move them to the VGPU provider.
        for consumer_uuid, alloc_data in allocations.items():
            # Copy and iterate over the current set of providers to avoid
            # modifying keys while iterating.
            allocs = alloc_data['allocations']
            for rp_uuid in list(allocs):
                resources = allocs[rp_uuid]['resources']
                if orc.VGPU in resources:
                    self._reshape_vgpu_allocations(
                        rp_uuid, root_node, consumer_uuid, alloc_data,
                        resources, pgpu_rps)

    def _update_provider_tree_for_vgpu(self, provider_tree, nodename,
                                       allocations=None):
        """Updates the provider tree for VGPU inventory.

        Before Stein, VGPU inventory and allocations were on the root compute
        node provider in the tree. Starting in Stein, the VGPU inventory is
        on a child provider in the tree. As a result, this method will
        "reshape" the tree if necessary on first start of this compute service
        in Stein.

        :param provider_tree: The ProviderTree to update.
        :param nodename: The ComputeNode.hypervisor_hostname, also known as
            the name of the root node provider in the tree for this host.
        :param allocations: If not None, indicates a reshape was requested and
            should be performed.
        :raises: nova.exception.ReshapeNeeded if ``allocations`` is None and
            the method determines a reshape of the tree is needed, i.e. VGPU
            inventory and allocations must be migrated from the root node
            provider to a child provider of VGPU resources in the tree.
        :raises: nova.exception.ReshapeFailed if the requested tree reshape
            fails for whatever reason.
        """
        # First, check if this host actually has vGPU to reshape
        inventories_dict = self._get_gpu_inventories()
        if not inventories_dict:
            return

        # Check to see if the root compute node provider in the tree for
        # this host already has VGPU inventory because if it does, and
        # we're not currently reshaping (allocations is None), we need
        # to indicate that a reshape is needed to move the VGPU inventory
        # onto a child provider in the tree.

        # Ensure GPU providers are in the ProviderTree for the given inventory.
        pgpu_rps = self._ensure_pgpu_providers(
            inventories_dict, provider_tree, nodename)

        if self._is_reshape_needed_vgpu_on_root(provider_tree, nodename):
            if allocations is None:
                # We have old VGPU inventory on root RP, but we haven't yet
                # allocations. That means we need to ask for a reshape.
                LOG.info('Requesting provider tree reshape in order to move '
                         'VGPU inventory from the root compute node provider '
                         '%s to a child provider.', nodename)
                raise exception.ReshapeNeeded()
            # We have allocations, that means we already asked for a reshape
            # and the Placement API returned us them. We now need to move
            # those from the root RP to the needed children RPs.
            root_node = provider_tree.data(nodename)
            # Reshape VGPU provider inventory and allocations, moving them
            # from the root node provider to the child providers.
            self._reshape_gpu_resources(allocations, root_node, pgpu_rps)
            # Only delete the root inventory once the reshape is done
            if orc.VGPU in root_node.inventory:
                del root_node.inventory[orc.VGPU]
                provider_tree.update_inventory(nodename, root_node.inventory)

    def _update_provider_tree_for_pcpu(self, provider_tree, nodename,
                                       allocations=None):
        """Updates the provider tree for PCPU inventory.

        Before Train, pinned instances consumed VCPU inventory just like
        unpinned instances. Starting in Train, these instances now consume PCPU
        inventory. The function can reshape the inventory, changing allocations
        of VCPUs to PCPUs.

        :param provider_tree: The ProviderTree to update.
        :param nodename: The ComputeNode.hypervisor_hostname, also known as
            the name of the root node provider in the tree for this host.
        :param allocations: A dict, keyed by consumer UUID, of allocation
            records, or None::

                {
                    $CONSUMER_UUID: {
                        "allocations": {
                            $RP_UUID: {
                                "generation": $RP_GEN,
                                "resources": {
                                    $RESOURCE_CLASS: $AMOUNT,
                                    ...
                                },
                            },
                            ...
                        },
                        "project_id": $PROJ_ID,
                        "user_id": $USER_ID,
                        "consumer_generation": $CONSUMER_GEN,
                    },
                    ...
                }

            If provided, this indicates a reshape was requested and should be
            performed.
        :raises: nova.exception.ReshapeNeeded if ``allocations`` is None and
            the method determines a reshape of the tree is needed, i.e. VCPU
            inventory and allocations must be migrated to PCPU resources.
        :raises: nova.exception.ReshapeFailed if the requested tree reshape
            fails for whatever reason.
        """
        # If we're not configuring PCPUs, then we've nothing to worry about
        # (yet)
        if not CONF.compute.cpu_dedicated_set:
            return

        root_node = provider_tree.data(nodename)

        # Similarly, if PCPU inventories are already reported then there is no
        # need to reshape
        if orc.PCPU in root_node.inventory:
            return

        ctx = nova_context.get_admin_context()
        compute_node = objects.ComputeNode.get_by_nodename(ctx, nodename)

        # Finally, if the compute node doesn't appear to support NUMA, move
        # swiftly on
        if not compute_node.numa_topology:
            return

        # The ComputeNode.numa_topology is a StringField, deserialize
        numa = objects.NUMATopology.obj_from_db_obj(compute_node.numa_topology)

        # If the host doesn't know of any pinned CPUs, we can continue
        if not any(cell.pinned_cpus for cell in numa.cells):
            return

        # At this point, we know there's something to be migrated here but not
        # how much. If the allocations are None, we're at the startup of the
        # compute node and a Reshape is needed. Indicate this by raising the
        # ReshapeNeeded exception

        if allocations is None:
            LOG.info(
                'Requesting provider tree reshape in order to move '
                'VCPU to PCPU allocations to the compute node '
                'provider %s', nodename)
            raise exception.ReshapeNeeded()

        # Go figure out how many VCPUs to migrate to PCPUs. We've been telling
        # people for years *not* to mix pinned and unpinned instances, meaning
        # we should be able to move all VCPUs to PCPUs, but we never actually
        # enforced this in code and there's an all-too-high chance someone
        # didn't get the memo

        allocations_needing_reshape = []

        # we need to tackle the allocations against instances on this host...

        instances = objects.InstanceList.get_by_host(
            ctx, compute_node.host, expected_attrs=['numa_topology'])
        for instance in instances:
            if not instance.numa_topology:
                continue

            if instance.numa_topology.cpu_policy != (
                fields.CPUAllocationPolicy.DEDICATED
            ):
                continue

            allocations_needing_reshape.append(instance.uuid)

        # ...and those for any migrations

        migrations = objects.MigrationList.get_in_progress_by_host_and_node(
            ctx, compute_node.host, compute_node.hypervisor_hostname)
        for migration in migrations:
            # we don't care about migrations that have landed here, since we
            # already have those instances above
            if not migration.dest_compute or (
                    migration.dest_compute == compute_node.host):
                continue

            instance = objects.Instance.get_by_uuid(
                ctx, migration.instance_uuid, expected_attrs=['numa_topology'])

            if not instance.numa_topology:
                continue

            if instance.numa_topology.cpu_policy != (
                fields.CPUAllocationPolicy.DEDICATED
            ):
                continue

            allocations_needing_reshape.append(migration.uuid)

        for allocation_uuid in allocations_needing_reshape:
            consumer_allocations = allocations.get(allocation_uuid, {}).get(
                'allocations', {})
            # TODO(stephenfin): We can probably just check the allocations for
            # ComputeNode.uuid since compute nodes are the only (?) provider of
            # VCPU and PCPU resources
            for rp_uuid in consumer_allocations:
                resources = consumer_allocations[rp_uuid]['resources']

                if orc.PCPU in resources or orc.VCPU not in resources:
                    # Either this has been migrated or it's not a compute node
                    continue

                # Switch stuff around. We can do a straight swap since an
                # instance is either pinned or unpinned. By doing this, we're
                # modifying the provided 'allocations' dict, which will
                # eventually be used by the resource tracker to update
                # placement
                resources['PCPU'] = resources['VCPU']
                del resources[orc.VCPU]

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

        data["vcpus"] = len(self._get_vcpu_available())
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

        data['pci_passthrough_devices'] = self._get_pci_passthrough_devices()

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
        :param instance: nova.db.main.models.Instance
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

        if not CONF.workarounds.skip_cpu_compare_on_dest:
            # Compare CPU
            try:
                if not instance.vcpu_model or not instance.vcpu_model.model:
                    source_cpu_info = src_compute_info['cpu_info']
                    self._compare_cpu(None, source_cpu_info, instance)
                else:
                    self._compare_cpu(instance.vcpu_model, None, instance)
            except exception.InvalidCPUInfo as e:
                raise exception.MigrationPreCheckError(reason=e)

        # Create file on storage, to be checked on source host
        filename = self._create_shared_storage_test_file(instance)

        data = objects.LibvirtLiveMigrateData()
        data.filename = filename
        data.image_type = CONF.libvirt.images_type
        data.graphics_listen_addr_vnc = CONF.vnc.server_listen
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
        data.dst_wants_file_backed_memory = CONF.libvirt.file_backed_memory > 0

        # TODO(artom) Set to indicate that the destination (us) can perform a
        # NUMA-aware live migration. NUMA-aware live migration will become
        # unconditionally supported in RPC 6.0, so this sentinel can be removed
        # then.
        if instance.numa_topology:
            data.dst_supports_numa_live_migration = True

        # NOTE(sean-k-mooney): The migrate_data vifs field is used to signal
        # that we are using the multiple port binding workflow so we can only
        # populate it if we are using multiple port bindings.
        # TODO(stephenfin): Remove once we can do this unconditionally in X or
        # later
        if self._network_api.supports_port_binding_extension(context):
            data.vifs = (
                migrate_data_obj.VIFMigrateData.create_skeleton_migrate_vifs(
                    instance.get_network_info()))
            for vif in data.vifs:
                vif.supports_os_vif_delegation = True

        return data

    def post_claim_migrate_data(self, context, instance, migrate_data, claim):
        migrate_data.dst_numa_info = self._get_live_migrate_numa_info(
            claim.claimed_numa_topology, claim.flavor, claim.image_meta)
        return migrate_data

    def _get_resources(self, instance, prefix=None):
        resources: 'objects.ResourceList' = []
        if prefix:
            migr_context = instance.migration_context
            attr_name = prefix + 'resources'
            if migr_context and attr_name in migr_context:
                resources = getattr(migr_context, attr_name) or []
        else:
            resources = instance.resources or []
        return resources

    def _get_vpmem_resources(self, resources):
        vpmem_resources = []
        for resource in resources:
            if 'metadata' in resource and \
                isinstance(resource.metadata, objects.LibvirtVPMEMDevice):
                vpmem_resources.append(resource)
        return vpmem_resources

    def _get_ordered_vpmem_resources(self, resources, flavor):
        vpmem_resources = self._get_vpmem_resources(resources)
        ordered_vpmem_resources = []
        labels = hardware.get_vpmems(flavor)
        for label in labels:
            for vpmem_resource in vpmem_resources:
                if vpmem_resource.metadata.label == label:
                    ordered_vpmem_resources.append(vpmem_resource)
                    vpmem_resources.remove(vpmem_resource)
                    break
        return ordered_vpmem_resources

    def _sorted_migrating_resources(self, instance, flavor):
        """This method is used to sort instance.migration_context.new_resources
        claimed on dest host, then the ordered new resources will be used to
        update resources info (e.g. vpmems) in the new xml which is used for
        live migration.
        """
        resources = self._get_resources(instance, prefix='new_')
        if not resources:
            return
        ordered_resources = []
        ordered_vpmem_resources = self._get_ordered_vpmem_resources(
                resources, flavor)
        ordered_resources.extend(ordered_vpmem_resources)
        ordered_resources_obj = objects.ResourceList(objects=ordered_resources)
        return ordered_resources_obj

    def _get_live_migrate_numa_info(self, instance_numa_topology, flavor,
                                    image_meta):
        """Builds a LibvirtLiveMigrateNUMAInfo object to send to the source of
        a live migration, containing information about how the instance is to
        be pinned on the destination host.

        :param instance_numa_topology: The InstanceNUMATopology as fitted to
                                       the destination by the live migration
                                       Claim.
        :param flavor: The Flavor object for the instance.
        :param image_meta: The ImageMeta object for the instance.
        :returns: A LibvirtLiveMigrateNUMAInfo object indicating how to update
                  the XML for the destination host.
        """
        info = objects.LibvirtLiveMigrateNUMAInfo()
        cpu_set, guest_cpu_tune, guest_cpu_numa, guest_numa_tune = \
            self._get_guest_numa_config(instance_numa_topology, flavor,
                                        image_meta)
        # NOTE(artom) These two should always be either None together, or
        # truth-y together.
        if guest_cpu_tune and guest_numa_tune:
            info.cpu_pins = {}
            for pin in guest_cpu_tune.vcpupin:
                info.cpu_pins[str(pin.id)] = pin.cpuset

            info.emulator_pins = guest_cpu_tune.emulatorpin.cpuset

            if guest_cpu_tune.vcpusched:
                # NOTE(artom) vcpusched is a list, but there's only ever one
                # element in it (see _get_guest_numa_config under
                # wants_realtime)
                info.sched_vcpus = guest_cpu_tune.vcpusched[0].vcpus
                info.sched_priority = guest_cpu_tune.vcpusched[0].priority

            info.cell_pins = {}
            for node in guest_numa_tune.memnodes:
                info.cell_pins[str(node.cellid)] = set(node.nodeset)

        LOG.debug('Built NUMA live migration info: %s', info)
        return info

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
        :param instance: nova.db.main.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
        :param block_device_info: result of _get_instance_block_device_info
        :returns: a LibvirtLiveMigrateData object
        """
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

        # TODO(artom) Set to indicate that the source (us) can perform a
        # NUMA-aware live migration. NUMA-aware live migration will become
        # unconditionally supported in RPC 6.0, so this sentinel can be removed
        # then.
        if instance.numa_topology:
            dest_check_data.src_supports_numa_live_migration = True

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

        :param guest_cpu: nova.objects.VirtCPUModel
            or nova.virt.libvirt.vconfig.LibvirtConfigGuestCPU or None.
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
        elif isinstance(guest_cpu, vconfig.LibvirtConfigGuestCPU):
            cpu = guest_cpu
        else:
            cpu = self._vcpu_model_to_cpu_config(guest_cpu)

        host_cpu = self._host.get_capabilities().host.cpu
        if host_cpu.arch == fields.Architecture.AARCH64:
            if self._host.has_min_version(MIN_LIBVIRT_AARCH64_CPU_COMPARE):
                LOG.debug("On AArch64 hosts, source and destination host "
                          "CPUs are compared to check if they're compatible"
                          "(the only use-case supported by libvirt for "
                          "Arm64/AArch64)")
                cpu = host_cpu
            else:
                LOG.debug("You need %s libvirt version to be able to compare "
                          "source host CPU with destination host CPU; skip "
                          "CPU comparison", MIN_LIBVIRT_AARCH64_CPU_COMPARE)
                return

        u = ("http://libvirt.org/html/libvirt-libvirt-host.html#"
             "virCPUCompareResult")
        m = _("CPU doesn't have compatibility.\n\n%(ret)s\n\nRefer to %(u)s")
        # unknown character exists in xml, then libvirt complains
        try:
            cpu_xml = cpu.to_xml()
            LOG.debug("cpu compare xml: %s", cpu_xml, instance=instance)
            ret = self._host.compare_hypervisor_cpu(cpu_xml)
        except libvirt.libvirtError as e:
            error_code = e.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                LOG.debug("URI %(uri)s does not support cpu comparison. "
                          "It will be proceeded though. Error: %(error)s",
                          {'uri': self._uri(), 'error': e})
                return
            else:
                LOG.error(m, {'ret': e, 'u': u})
                raise exception.InvalidCPUInfo(
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

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Spawning live_migration operation for distributing high-load.

        :param context: security context
        :param instance:
            nova.db.main.models.Instance object
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
        # exploit the URI accepted by libvirt
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
            LOG.error("Failed to cancel migration %s",
                    encodeutils.exception_to_unicode(e), instance=instance)
            raise

    def _verify_serial_console_is_disabled(self):
        if CONF.serial_console.enabled:

            msg = _('Your destination node does not support'
                    ' retrieving listen addresses. In order'
                    ' for live migration to work properly you'
                    ' must disable serial console.')
            raise exception.MigrationError(reason=msg)

    def _detach_direct_passthrough_vifs(self, context,
                                        migrate_data, instance):
        """detaches passthrough vif to enable live migration

        :param context: security context
        :param migrate_data: a LibvirtLiveMigrateData object
        :param instance: instance object that is migrated.
        """
        # NOTE(sean-k-mooney): if we have vif data available we
        # loop over each vif and detach all direct passthrough
        # vifs to allow sriov live migration.
        direct_vnics = network_model.VNIC_TYPES_DIRECT_PASSTHROUGH
        vifs = [vif.source_vif for vif in migrate_data.vifs
                if "source_vif" in vif and vif.source_vif]
        for vif in vifs:
            if vif['vnic_type'] in direct_vnics:
                LOG.info("Detaching vif %s from instance "
                         "%s for live migration", vif['id'], instance.id)
                self.detach_interface(context, instance, vif)

    def _live_migration_operation(self, context, instance, dest,
                                  block_migration, migrate_data, guest,
                                  device_names):
        """Invoke the live migration operation

        :param context: security context
        :param instance:
            nova.db.main.models.Instance object
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

            if not migrate_data.serial_listen_addr:
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

            new_xml_str = None
            if CONF.libvirt.virt_type != "parallels":
                # If the migrate_data has port binding information for the
                # destination host, we need to prepare the guest vif config
                # for the destination before we start migrating the guest.
                get_vif_config = None
                if 'vifs' in migrate_data and migrate_data.vifs:
                    # NOTE(mriedem): The vif kwarg must be built on the fly
                    # within get_updated_guest_xml based on migrate_data.vifs.
                    # We could stash the virt_type from the destination host
                    # into LibvirtLiveMigrateData but the host kwarg is a
                    # nova.virt.libvirt.host.Host object and is used to check
                    # information like libvirt version on the destination.
                    # If this becomes a problem, what we could do is get the
                    # VIF configs while on the destination host during
                    # pre_live_migration() and store those in the
                    # LibvirtLiveMigrateData object. For now we just use the
                    # source host information for virt_type and
                    # host (version) since the conductor live_migrate method
                    # _check_compatible_with_source_hypervisor() ensures that
                    # the hypervisor types and versions are compatible.
                    get_vif_config = functools.partial(
                        self.vif_driver.get_config,
                        instance=instance,
                        image_meta=instance.image_meta,
                        flavor=instance.flavor,
                        virt_type=CONF.libvirt.virt_type,
                    )
                    self._detach_direct_passthrough_vifs(context,
                        migrate_data, instance)
                new_resources = None
                if isinstance(instance, objects.Instance):
                    new_resources = self._sorted_migrating_resources(
                        instance, instance.flavor)
                new_xml_str = libvirt_migrate.get_updated_guest_xml(
                    # TODO(sahid): It's not a really good idea to pass
                    # the method _get_volume_config and we should to find
                    # a way to avoid this in future.
                    instance, guest, migrate_data, self._get_volume_config,
                    get_vif_config=get_vif_config, new_resources=new_resources)

            # NOTE(pkoniszewski): Because of precheck which blocks
            # tunnelled block live migration with mapped volumes we
            # can safely remove migrate_disks when tunnelling is on.
            # Otherwise we will block all tunnelled block migrations,
            # even when an instance does not have volumes mapped.
            # This is because selective disk migration is not
            # supported in tunnelled block live migration. Also we
            # cannot fallback to migrateToURI2 in this case because of
            # bug #1398999
            #
            # TODO(kchamart) Move the following bit to guest.migrate()
            if (migration_flags & libvirt.VIR_MIGRATE_TUNNELLED != 0):
                device_names = []

            # TODO(sahid): This should be in
            # post_live_migration_at_source but no way to retrieve
            # ports acquired on the host for the guest at this
            # step. Since the domain is going to be removed from
            # libvird on source host after migration, we backup the
            # serial ports to release them if all went well.
            serial_ports = []
            if CONF.serial_console.enabled:
                serial_ports = list(self._get_serial_ports_from_guest(guest))

            LOG.debug("About to invoke the migrate API", instance=instance)
            guest.migrate(self._live_migration_uri(dest),
                          migrate_uri=migrate_uri,
                          flags=migration_flags,
                          migrate_disks=device_names,
                          destination_xml=new_xml_str,
                          bandwidth=CONF.libvirt.live_migration_bandwidth)
            LOG.debug("Migrate API has completed", instance=instance)

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

        if (self._block_migration_flags &
                libvirt.VIR_MIGRATE_TUNNELLED == 0):
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

        on_migration_failure: ty.Deque[str] = deque()
        data_gb = self._live_migration_data_gb(instance, disk_paths)
        downtime_steps = list(libvirt_migrate.downtime_steps(data_gb))
        migration = migrate_data.migration
        curdowntime = None

        migration_flags = self._get_migration_flags(
                                  migrate_data.block_migration)

        n = 0
        start = time.time()
        is_post_copy_enabled = self._is_post_copy_enabled(migration_flags)
        # vpmem does not support post copy
        is_post_copy_enabled &= not bool(self._get_vpmems(instance))
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

                completion_timeout = int(
                    CONF.libvirt.live_migration_completion_timeout * data_gb)
                # NOTE(yikun): Check the completion timeout to determine
                # should trigger the timeout action, and there are two choices
                # ``abort`` (default) or ``force_complete``. If the action is
                # set to ``force_complete``, the post-copy will be triggered
                # if available else the VM will be suspended, otherwise the
                # live migrate operation will be aborted.
                if libvirt_migrate.should_trigger_timeout_action(
                        instance, elapsed, completion_timeout,
                        migration.status):
                    timeout_act = CONF.libvirt.live_migration_timeout_action
                    if timeout_act == 'force_complete':
                        self.live_migration_force_complete(instance)
                    else:
                        # timeout action is 'abort'
                        try:
                            guest.abort_job()
                        except libvirt.libvirtError as e:
                            LOG.warning("Failed to abort migration %s",
                                    encodeutils.exception_to_unicode(e),
                                    instance=instance)
                            self._clear_empty_migration(instance)
                            raise

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

                    # NOTE(fanzhang): do not include disk transfer stats in
                    # the progress percentage calculation but log them.
                    disk_remaining = 100
                    if info.disk_total != 0:
                        disk_remaining = round(info.disk_remaining *
                                               100 / info.disk_total)

                    lg = LOG.debug
                    if (n % 60) == 0:
                        lg = LOG.info

                    lg("Migration running for %(secs)d secs, "
                       "memory %(remaining)d%% remaining "
                       "(bytes processed=%(processed_memory)d, "
                       "remaining=%(remaining_memory)d, "
                       "total=%(total_memory)d); "
                       "disk %(disk_remaining)d%% remaining "
                       "(bytes processed=%(processed_disk)d, "
                       "remaining=%(remaining_disk)d, "
                       "total=%(total_disk)d).",
                       {"secs": elapsed, "remaining": remaining,
                        "processed_memory": info.memory_processed,
                        "remaining_memory": info.memory_remaining,
                        "total_memory": info.memory_total,
                        "disk_remaining": disk_remaining,
                        "processed_disk": info.disk_processed,
                        "remaining_disk": info.disk_remaining,
                        "total_disk": info.disk_total}, instance=instance)

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
            nova.db.main.models.Instance object
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
            # NOTE(aarents): Ensure job is aborted if still running before
            # raising the exception so this would avoid the migration to be
            # done and the libvirt guest to be resumed on the target while
            # the instance record would still related to the source host.
            try:
                # If migration is running in post-copy mode and guest
                # already running on dest host, libvirt will refuse to
                # cancel migration job.
                self.live_migration_abort(instance)
            except libvirt.libvirtError:
                LOG.warning("Error occured when trying to abort live ",
                            "migration job, ignoring it.", instance=instance)
            raise
        finally:
            LOG.debug("Live migration monitoring is all done",
                      instance=instance)

    def _is_post_copy_enabled(self, migration_flags):
        return (migration_flags & libvirt.VIR_MIGRATE_POSTCOPY) != 0

    def live_migration_force_complete(self, instance):
        try:
            self.active_migrations[instance.uuid].append('force-complete')
        except KeyError:
            raise exception.NoActiveMigrationForInstance(
                instance_id=instance.uuid)

    def _try_fetch_image(self, context, path, image_id, instance,
                         fallback_from_host=None):
        try:
            libvirt_utils.fetch_image(context, path, image_id,
                                      instance.trusted_certs)
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

    def _reattach_instance_vifs(self, context, instance, network_info):
        guest = self._host.get_guest(instance)
        # validate that the guest has the expected number of interfaces
        # attached.
        guest_interfaces = guest.get_interfaces()
        # NOTE(sean-k-mooney): In general len(guest_interfaces) will
        # be equal to len(network_info) as interfaces will not be hot unplugged
        # unless they are SR-IOV direct mode interfaces. As such we do not
        # need an else block here as it would be a noop.
        if len(guest_interfaces) < len(network_info):
            # NOTE(sean-k-mooney): we are doing a post live migration
            # for a guest with sriov vif that were detached as part of
            # the migration. loop over the vifs and attach the missing
            # vif as part of the post live migration phase.
            direct_vnics = network_model.VNIC_TYPES_DIRECT_PASSTHROUGH
            for vif in network_info:
                if vif['vnic_type'] in direct_vnics:
                    LOG.info("Attaching vif %s to instance %s",
                             vif['id'], instance.id)
                    self.attach_interface(context, instance,
                                          instance.image_meta, vif)

    def rollback_live_migration_at_source(self, context, instance,
                                          migrate_data):
        """reconnect sriov interfaces after failed live migration
        :param context: security context
        :param instance:  the instance being migrated
        :param migrate_date: a LibvirtLiveMigrateData object
        """
        network_info = network_model.NetworkInfo(
            [vif.source_vif for vif in migrate_data.vifs
                            if "source_vif" in vif and vif.source_vif])
        self._reattach_instance_vifs(context, instance, network_info)

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
                if (migrate_data.obj_attr_is_set("serial_listen_ports") and
                        migrate_data.serial_listen_ports):
                    # Releases serial ports reserved.
                    for port in migrate_data.serial_listen_ports:
                        serial_console.release_port(
                            host=migrate_data.serial_listen_addr, port=port)

            if not is_shared_instance_path:
                instance_dir = libvirt_utils.get_instance_path_at_destination(
                    instance, migrate_data)
                if os.path.exists(instance_dir):
                    shutil.rmtree(instance_dir)

    def _pre_live_migration_plug_vifs(self, instance, network_info,
                                      migrate_data):
        if 'vifs' in migrate_data and migrate_data.vifs:
            LOG.debug('Plugging VIFs using destination host port bindings '
                      'before live migration.', instance=instance)
            vif_plug_nw_info = network_model.NetworkInfo([])
            for migrate_vif in migrate_data.vifs:
                vif_plug_nw_info.append(migrate_vif.get_dest_vif())
        else:
            LOG.debug('Plugging VIFs before live migration.',
                      instance=instance)
            vif_plug_nw_info = network_info
        # Retry operation is necessary because continuous live migration
        # requests to the same host cause concurrent requests to iptables,
        # then it complains.
        max_retry = CONF.live_migration_retry_count
        for cnt in range(max_retry):
            try:
                self.plug_vifs(instance, vif_plug_nw_info)
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
                with open(image_disk_info_path, 'w') as f:
                    f.write(jsonutils.dumps(image_disk_info))

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
            self._connect_volume(context, connection_info, instance)

        self._pre_live_migration_plug_vifs(
            instance, network_info, migrate_data)

        # Store server_listen and latest disk device info
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
            for port in range(num_ports):
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
                volume_secret = self._host.find_secret('volume', vol.volume_id)
                if volume_secret:
                    bdmi.encryption_secret_uuid = volume_secret.UUIDString()

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
                        size=size,
                        trusted_certs=instance.trusted_certs)
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
            image.cache(fetch_func=copy_from_host, size=size,
                        filename=filename)

        # NOTE(lyarwood): If the instance vm_state is shelved offloaded then we
        # must be unshelving for _try_fetch_image_cache to be called.
        # NOTE(mriedem): Alternatively if we are doing a cross-cell move of a
        # non-volume-backed server and finishing (spawning) on the dest host,
        # we have to flatten the rbd image so we can delete the temporary
        # snapshot in the compute manager.
        mig_context = instance.migration_context
        cross_cell_move = (
                mig_context and mig_context.is_cross_cell_move() or False)
        if instance.vm_state == vm_states.SHELVED_OFFLOADED or cross_cell_move:
            # NOTE(lyarwood): When using the rbd imagebackend the call to cache
            # above will attempt to clone from the shelved snapshot in Glance
            # if available from this compute. We then need to flatten the
            # resulting image to avoid it still referencing and ultimately
            # blocking the removal of the shelved snapshot at the end of the
            # unshelve. This is a no-op for all but the rbd imagebackend.
            action = (
                'migrating instance across cells' if cross_cell_move
                else 'unshelving instance')
            try:
                image.flatten()
                LOG.debug('Image %s flattened successfully while %s.',
                          image.path, action, instance=instance)
            except NotImplementedError:
                # NOTE(lyarwood): There's an argument to be made for logging
                # our inability to call flatten here, however given this isn't
                # implemented for most of the backends it may do more harm than
                # good, concerning operators etc so for now just pass.
                pass

    def _create_images_and_backing(self, context, instance, instance_dir,
                                   disk_info, fallback_from_host=None):
        """:param context: security context
           :param instance:
               nova.db.main.models.Instance object
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
                    flavor = instance.get_flavor()
                    swap_mb = flavor.swap
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
        # NOTE(mdbooth): The block_device_info we were passed was initialized
        # with BDMs from the source host before they were updated to point to
        # the destination. We can safely use this to disconnect the source
        # without re-fetching.
        block_device_mapping = driver.block_device_info_get_mapping(
                block_device_info)

        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            # NOTE(lyarwood): Ignore exceptions here to avoid the instance
            # being left in an ERROR state and still marked on the source.
            try:
                self._disconnect_volume(context, connection_info, instance)
            except Exception:
                volume_id = driver_block_device.get_volume_id(connection_info)
                LOG.exception("Ignoring exception while attempting to "
                              "disconnect volume %s from the source host "
                              "during post_live_migration", volume_id,
                              instance=instance)

    def post_live_migration_at_source(self, context, instance, network_info):
        """Unplug VIFs from networks at source.

        :param context: security context
        :param instance: instance object reference
        :param network_info: instance network information
        """
        self.unplug_vifs(instance, network_info)

    def _qemu_monitor_announce_self(self, instance):
        """Send announce_self command to QEMU monitor.

        This is to trigger generation of broadcast RARP frames to
        update network switches. This is best effort.
        """
        if not CONF.workarounds.enable_qemu_monitor_announce_self:
            return

        LOG.info('Sending announce-self command to QEMU monitor',
                 instance=instance)

        try:
            guest = self._host.get_guest(instance)
            guest.announce_self()
        except Exception:
            LOG.warning('Failed to send announce-self command to QEMU monitor',
                        instance=instance)
            LOG.exception()

    def post_live_migration_at_destination(self, context,
                                           instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :param context: security context
        :param instance:
            nova.db.main.models.Instance object
            instance object that is migrated.
        :param network_info: instance network information
        :param block_migration: if true, post operation of block_migration.
        """
        self._reattach_instance_vifs(context, instance, network_info)
        self._qemu_monitor_announce_self(instance)

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

        if (
            CONF.libvirt.virt_type == 'parallels' and
            guest_config.os_type == fields.VMMode.EXE
        ):
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
                over_commit_size = max(0, int(virt_size) - dk_size)

            elif disk_type == 'file':
                dk_size = os.stat(path).st_blocks * 512
                virt_size = os.path.getsize(path)
                backing_file = ""
                over_commit_size = int(virt_size) - dk_size

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
                         'ex': encodeutils.exception_to_unicode(ex)},
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
                     'ex': encodeutils.exception_to_unicode(ex)})
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
            except (exception.VolumeBDMPathNotFound,
                    exception.DiskNotFound) as e:
                if isinstance(e, exception.VolumeBDMPathNotFound):
                    thing = 'backing volume block device'
                elif isinstance(e, exception.DiskNotFound):
                    thing = 'backing disk storage'

                LOG.warning('Periodic task is updating the host stats, '
                            'it is trying to get disk info for %(i_name)s, '
                            'but the %(thing)s was removed by a concurrent '
                            'operation such as resize. Error: %(error)s',
                            {'i_name': guest.name, 'thing': thing, 'error': e})

            # NOTE(gtt116): give other tasks a chance.
            greenthread.sleep(0)
        return disk_over_committed_size

    def get_available_nodes(self, refresh=False):
        return [self._host.get_hostname()]

    def get_host_cpu_stats(self):
        """Return the current CPU state of the host."""
        return self._host.get_cpu_stats()

    def get_host_uptime(self):
        """Returns the result of calling "uptime"."""
        out, err = processutils.execute('env', 'LANG=C', 'uptime')
        return out

    def manage_image_cache(self, context, all_instances):
        """Manage the local cache of images."""
        self.image_cache_manager.update(context, all_instances)

    def _cleanup_remote_migration(self, dest, inst_base, inst_base_resize,
                                  shared_storage=False):
        """Used only for cleanup in case migrate_disk_and_power_off fails."""
        try:
            if os.path.exists(inst_base_resize):
                shutil.rmtree(inst_base, ignore_errors=True)
                os.rename(inst_base_resize, inst_base)
                if not shared_storage:
                    self._remotefs.remove_dir(dest, inst_base)
        except Exception:
            pass

    def cache_image(self, context, image_id):
        cache_dir = os.path.join(CONF.instances_path,
                                 CONF.image_cache.subdirectory_name)
        path = os.path.join(cache_dir,
                            imagecache.get_cache_fname(image_id))
        if os.path.exists(path):
            LOG.info('Image %(image_id)s already cached; updating timestamp',
                     {'image_id': image_id})
            # NOTE(danms): The regular image cache routines use a wrapper
            # (_update_utime_ignore_eacces()) around this to avoid failing
            # on permissions (which may or may not be legit due to an NFS
            # race). However, since this is best-effort, errors are swallowed
            # by compute manager per-image, and we are compelled to report
            # errors up our stack, we use the raw method here to avoid the
            # silent ignore of the EACCESS.
            nova.privsep.path.utime(path)
            return False
        else:
            # NOTE(danms): In case we are running before the first boot, make
            # sure the cache directory is created
            if not os.path.isdir(cache_dir):
                fileutils.ensure_tree(cache_dir)
            LOG.info('Caching image %(image_id)s by request',
                     {'image_id': image_id})
            # NOTE(danms): The imagebackend code, as called via spawn() where
            # images are normally cached, uses a lock on the root disk it is
            # creating at the time, but relies on the
            # compute_utils.disk_ops_semaphore for cache fetch mutual
            # exclusion, which is grabbed in images.fetch() (which is called
            # by images.fetch_to_raw() below). So, by calling fetch_to_raw(),
            # we are sharing the same locking for the cache fetch as the
            # rest of the code currently called only from spawn().
            images.fetch_to_raw(context, image_id, path)
            return True

    def _get_disk_size_reserved_for_image_cache(self):
        """Return the amount of DISK_GB resource need to be reserved for the
        image cache.

        :returns: The disk space in GB
        """
        if not CONF.workarounds.reserve_disk_resource_for_image_cache:
            return 0

        return compute_utils.convert_mb_to_ceil_gb(
            self.image_cache_manager.get_disk_usage() / 1024.0 / 1024.0)

    def _is_path_shared_with(self, dest, path):
        # NOTE (rmk): There are two methods of determining whether we are
        #             on the same filesystem: the source and dest IP are the
        #             same, or we create a file on the dest system via SSH
        #             and check whether the source system can also see it.
        shared_path = (dest == self.get_host_ip_addr())
        if not shared_path:
            tmp_file = uuidutils.generate_uuid(dashed=False) + '.tmp'
            tmp_path = os.path.join(path, tmp_file)

            try:
                self._remotefs.create_file(dest, tmp_path)
                if os.path.exists(tmp_path):
                    shared_path = True
                    os.unlink(tmp_path)
                else:
                    self._remotefs.remove_file(dest, tmp_path)
            except Exception:
                pass
        return shared_path

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
        shared_instance_path = self._is_path_shared_with(dest, inst_base)

        # try to create the directory on the remote compute node
        # if this fails we pass the exception up the stack so we can catch
        # failures here earlier
        if not shared_instance_path:
            try:
                self._remotefs.create_dir(dest, inst_base)
            except processutils.ProcessExecutionError as e:
                reason = _("not able to execute ssh command: %s") % e
                raise exception.InstanceFaultRollback(
                    exception.ResizeError(reason=reason))

        self.power_off(instance, timeout, retry_interval)
        self.unplug_vifs(instance, network_info)
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            self._disconnect_volume(context, connection_info, instance)

        disk_info = self._get_instance_disk_info(instance, block_device_info)

        try:
            # If cleanup failed in previous resize attempts we try to remedy
            # that before a resize is tried again
            self._cleanup_failed_instance_base(inst_base_resize)
            os.rename(inst_base, inst_base_resize)
            # if we are migrating the instance with shared instance path then
            # create the directory.  If it is a remote node the directory
            # has already been created
            if shared_instance_path:
                dest = None
                fileutils.ensure_tree(inst_base)

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

            # Handle migration of vTPM data if needed
            libvirt_utils.save_and_migrate_vtpm_dir(
                instance.uuid, inst_base_resize, inst_base, dest,
                on_execute, on_completion)

        except Exception:
            with excutils.save_and_reraise_exception():
                self._cleanup_remote_migration(dest, inst_base,
                                               inst_base_resize,
                                               shared_instance_path)

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
        images.convert_image(path, path_qcow, 'raw', 'qcow2')
        os.rename(path_qcow, path)

    def _finish_migration_vtpm(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ) -> None:
        """Handle vTPM when migrating or resizing an instance.

        Handle the case where we're resizing between different versions of TPM,
        or enabling/disabling TPM.
        """
        old_vtpm_config = hardware.get_vtpm_constraint(
            instance.old_flavor, instance.image_meta)
        new_vtpm_config = hardware.get_vtpm_constraint(
            instance.new_flavor, instance.image_meta)

        if old_vtpm_config:
            # we had a vTPM in the old flavor; figure out if we need to do
            # anything with it
            inst_base = libvirt_utils.get_instance_path(instance)
            swtpm_dir = os.path.join(inst_base, 'swtpm', instance.uuid)
            copy_swtpm_dir = True

            if old_vtpm_config != new_vtpm_config:
                # we had vTPM in the old flavor but the new flavor either
                # doesn't or has different config; delete old TPM data and let
                # libvirt create new data
                if os.path.exists(swtpm_dir):
                    LOG.info(
                        'Old flavor and new flavor have different vTPM '
                        'configuration; removing existing vTPM data.')
                    copy_swtpm_dir = False
                    shutil.rmtree(swtpm_dir)

            # apparently shutil.rmtree() isn't reliable on NFS so don't rely
            # only on path existance here.
            if copy_swtpm_dir and os.path.exists(swtpm_dir):
                libvirt_utils.restore_vtpm_dir(swtpm_dir)
        elif new_vtpm_config:
            # we've requested vTPM in the new flavor and didn't have one
            # previously so we need to create a new secret
            crypto.ensure_vtpm_secret(context, instance)

    def finish_migration(
        self,
        context: nova_context.RequestContext,
        migration: 'objects.Migration',
        instance: 'objects.Instance',
        disk_info: str,
        network_info: network_model.NetworkInfo,
        image_meta: 'objects.ImageMeta',
        resize_instance: bool,
        allocations: ty.Dict[str, ty.Any],
        block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
        power_on: bool = True,
    ) -> None:
        """Complete the migration process on the destination host."""
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
        for info in jsonutils.loads(disk_info):
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

        # Does the guest need to be assigned some vGPU mediated devices ?
        mdevs = self._allocate_mdevs(allocations)

        # Handle the case where the guest has emulated TPM
        self._finish_migration_vtpm(context, instance)

        xml = self._get_guest_xml(context, instance, network_info,
                                  block_disk_info, image_meta,
                                  block_device_info=block_device_info,
                                  mdevs=mdevs)
        # NOTE(mriedem): vifs_already_plugged=True here, regardless of whether
        # or not we've migrated to another host, because we unplug VIFs locally
        # and the status change in the port might go undetected by the neutron
        # L2 agent (or neutron server) so neutron may not know that the VIF was
        # unplugged in the first place and never send an event.
        guest = self._create_guest_with_network(
            context, xml, instance, network_info, block_device_info,
            power_on=power_on, vifs_already_plugged=True,
            post_xml_callback=gen_confdrive)
        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

            # Sync guest time after migration.
            guest.sync_guest_time()

        LOG.debug("finish_migration finished successfully.", instance=instance)

    def _cleanup_failed_instance_base(self, inst_base):
        """Make sure that a failed migrate or resize doesn't prevent us from
        rolling back in a revert or retrying a resize.
        """
        try:
            shutil.rmtree(inst_base)
        except OSError as e:
            if e.errno != errno.ENOENT:
                raise

    def _finish_revert_migration_vtpm(
        self,
        context: nova_context.RequestContext,
        instance: 'objects.Instance',
    ) -> None:
        """Handle vTPM differences when reverting a migration or resize.

        We should either restore any emulated vTPM persistent storage files or
        create new ones.
        """
        old_vtpm_config = hardware.get_vtpm_constraint(
            instance.old_flavor, instance.image_meta)
        new_vtpm_config = hardware.get_vtpm_constraint(
            instance.new_flavor, instance.image_meta)

        if old_vtpm_config:
            # the instance had a vTPM before resize and should have one again;
            # move the previously-saved vTPM data back to its proper location
            inst_base = libvirt_utils.get_instance_path(instance)
            swtpm_dir = os.path.join(inst_base, 'swtpm', instance.uuid)
            if os.path.exists(swtpm_dir):
                libvirt_utils.restore_vtpm_dir(swtpm_dir)
        elif new_vtpm_config:
            # the instance gained a vTPM and must now lose it; delete the vTPM
            # secret, knowing that libvirt will take care of everything else on
            # the destination side
            crypto.delete_vtpm_secret(context, instance)

    def finish_revert_migration(
        self,
        context: nova.context.RequestContext,
        instance: 'objects.Instance',
        network_info: network_model.NetworkInfo,
        migration: 'objects.Migration',
        block_device_info: ty.Optional[ty.Dict[str, ty.Any]] = None,
        power_on: bool = True,
    ) -> None:
        """Finish the second half of reverting a resize on the source host."""
        LOG.debug('Starting finish_revert_migration', instance=instance)

        inst_base = libvirt_utils.get_instance_path(instance)
        inst_base_resize = inst_base + "_resize"

        # NOTE(danms): if we're recovering from a failed migration,
        # make sure we don't have a left-over same-host base directory
        # that would conflict. Also, don't fail on the rename if the
        # failure happened early.
        if os.path.exists(inst_base_resize):
            self._cleanup_failed_instance_base(inst_base)
            os.rename(inst_base_resize, inst_base)

        root_disk = self.image_backend.by_name(instance, 'disk')
        # Once we rollback, the snapshot is no longer needed, so remove it
        if root_disk.exists():
            root_disk.rollback_to_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)
            root_disk.remove_snap(libvirt_utils.RESIZE_SNAPSHOT_NAME)

        self._finish_revert_migration_vtpm(context, instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            instance.image_meta,
                                            block_device_info)

        # The guest could already have mediated devices, using them for
        # the new XML
        mdevs = list(self._get_all_assigned_mediated_devices(instance))

        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  instance.image_meta,
                                  block_device_info=block_device_info,
                                  mdevs=mdevs)
        self._create_guest_with_network(
            context, xml, instance, network_info, block_device_info,
            power_on=power_on)

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
        result: ty.Dict[str, ty.List[str]] = {"volumes": [], "ifaces": []}
        try:
            doc = etree.fromstring(xml_doc)
        except Exception:
            return result
        blocks = [('./devices/disk', 'volumes'),
            ('./devices/interface', 'ifaces')]
        for block, key in blocks:
            section = doc.findall(block)
            for node in section:
                for child in node:
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
        state, max_mem, mem, num_cpu, cpu_time = guest._get_domain_info()
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

        for interface in xml_doc.findall('./devices/interface'):
            mac_address = interface.find('mac').get('address')
            target = interface.find('./target')

            # add nic that has no target (therefore no stats)
            if target is None:
                diags.add_nic(mac_address=mac_address)
                continue

            # add nic with stats
            dev = target.get('dev')
            try:
                if dev:
                    # interfaceStats might launch an exception if the
                    # method is not supported by the underlying hypervisor
                    # being used by libvirt
                    stats = domain.interfaceStats(dev)
                    diags.add_nic(mac_address=mac_address,
                                  rx_octets=stats[0],
                                  rx_errors=stats[2],
                                  rx_drop=stats[3],
                                  rx_packets=stats[1],
                                  tx_octets=stats[4],
                                  tx_errors=stats[6],
                                  tx_drop=stats[7],
                                  tx_packets=stats[5])

            except libvirt.libvirtError:
                pass

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

    def _build_interface_metadata(self, dev, vifs_to_expose, vlans_by_mac,
                                  trusted_by_mac):
        """Builds a metadata object for a network interface

        :param dev: The LibvirtConfigGuestInterface to build metadata for.
        :param vifs_to_expose: The list of tagged and/or vlan'ed
                               VirtualInterface objects.
        :param vlans_by_mac: A dictionary of mac address -> vlan associations.
        :param trusted_by_mac: A dictionary of mac address -> vf_trusted
                               associations.
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
        device.vf_trusted = trusted_by_mac.get(vif.address, False)
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
        trusted_by_mac = netutils.get_cached_vifs_with_trusted(network_info)
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
                                                        vlans_by_mac,
                                                        trusted_by_mac)
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
        pass

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
                os.rename(target, target_del)
                break
            except Exception:
                pass
            try:
                os.rename(target_resize, target_del)
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
                LOG.info(
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
            LOG.info(
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
        return fs_type in [nova.privsep.fs.FS_FORMAT_EXT2,
                           nova.privsep.fs.FS_FORMAT_EXT3,
                           nova.privsep.fs.FS_FORMAT_EXT4,
                           nova.privsep.fs.FS_FORMAT_XFS]

    def _get_tpm_traits(self) -> ty.Dict[str, bool]:
        # Assert or deassert TPM support traits
        return {
            ot.COMPUTE_SECURITY_TPM_2_0: CONF.libvirt.swtpm_enabled,
            ot.COMPUTE_SECURITY_TPM_1_2: CONF.libvirt.swtpm_enabled,
        }

    def _get_vif_model_traits(self) -> ty.Dict[str, bool]:
        """Get vif model traits based on the currently enabled virt_type.

        Not all traits generated by this function may be valid and the result
        should be validated.

        :return: A dict of trait names mapped to boolean values.
        """
        all_models = set(itertools.chain(
            *libvirt_vif.SUPPORTED_VIF_MODELS.values()
        ))
        supported_models = libvirt_vif.SUPPORTED_VIF_MODELS.get(
            CONF.libvirt.virt_type, []
        )
        # construct the corresponding standard trait from the VIF model name
        return {
            f'COMPUTE_NET_VIF_MODEL_{model.replace("-", "_").upper()}': model
            in supported_models for model in all_models
        }

    def _get_storage_bus_traits(self) -> ty.Dict[str, bool]:
        """Get storage bus traits based on the currently enabled virt_type.

        For QEMU and KVM this function uses the information returned by the
        libvirt domain capabilities API. For other virt types we generate the
        traits based on the static information in the blockinfo module.

        Not all traits generated by this function may be valid and the result
        should be validated.

        :return: A dict of trait names mapped to boolean values.
        """
        all_buses = set(itertools.chain(
            *blockinfo.SUPPORTED_DEVICE_BUSES.values()
        ))

        if CONF.libvirt.virt_type in ('qemu', 'kvm'):
            dom_caps = self._host.get_domain_capabilities()
            supported_buses: ty.Set[str] = set()
            for arch_type in dom_caps:
                for machine_type in dom_caps[arch_type]:
                    supported_buses.update(
                        dom_caps[arch_type][machine_type].devices.disk.buses
                    )
        else:
            supported_buses = blockinfo.SUPPORTED_DEVICE_BUSES.get(
                CONF.libvirt.virt_type, []
            )

        # construct the corresponding standard trait from the storage bus name
        return {
            f'COMPUTE_STORAGE_BUS_{bus.replace("-", "_").upper()}': bus in
            supported_buses for bus in all_buses
        }

    def _get_video_model_traits(self) -> ty.Dict[str, bool]:
        """Get video model traits from libvirt.

        Not all traits generated by this function may be valid and the result
        should be validated.

        :return: A dict of trait names mapped to boolean values.
        """
        all_models = fields.VideoModel.ALL

        dom_caps = self._host.get_domain_capabilities()
        supported_models: ty.Set[str] = set()
        for arch_type in dom_caps:
            for machine_type in dom_caps[arch_type]:
                supported_models.update(
                    dom_caps[arch_type][machine_type].devices.video.models
                )

        # construct the corresponding standard trait from the video model name
        return {
            f'COMPUTE_GRAPHICS_MODEL_{model.replace("-", "_").upper()}': model
            in supported_models for model in all_models
        }

    def _get_cpu_traits(self) -> ty.Dict[str, bool]:
        """Get CPU-related traits to be set and unset on the host's resource
        provider.

        :return: A dict of trait names mapped to boolean values.
        """
        traits = self._get_cpu_feature_traits()
        traits[ot.HW_CPU_X86_AMD_SEV] = self._host.supports_amd_sev
        traits[ot.HW_CPU_HYPERTHREADING] = self._host.has_hyperthreading

        return traits

    def _get_cpu_feature_traits(self) -> ty.Dict[str, bool]:
        """Get CPU traits of VMs based on guest CPU model config.

        1. If mode is 'host-model' or 'host-passthrough', use host's
           CPU features.
        2. If mode is None, choose a default CPU model based on CPU
           architecture.
        3. If mode is 'custom', use cpu_models to generate CPU features.

        The code also accounts for cpu_model_extra_flags configuration when
        cpu_mode is 'host-model', 'host-passthrough' or 'custom', this
        ensures user specified CPU feature flags to be included.

        :return: A dict of trait names mapped to boolean values.
        """
        cpu = self._get_guest_cpu_model_config()
        if not cpu:
            LOG.info('The current libvirt hypervisor %(virt_type)s '
                     'does not support reporting CPU traits.',
                     {'virt_type': CONF.libvirt.virt_type})
            return {}

        caps = deepcopy(self._host.get_capabilities())
        if cpu.mode in ('host-model', 'host-passthrough'):
            # Account for features in cpu_model_extra_flags conf
            host_features: ty.Set[str] = {
                f.name for f in caps.host.cpu.features | cpu.features
            }
            return libvirt_utils.cpu_features_to_traits(host_features)

        def _resolve_features(cpu):
            xml_str = cpu.to_xml()
            features_xml = self._get_guest_baseline_cpu_features(xml_str)
            feature_names = []
            if features_xml:
                cpu = vconfig.LibvirtConfigCPU()
                cpu.parse_str(features_xml)
                feature_names = [f.name for f in cpu.features]
            return feature_names

        features: ty.Set[str] = set()
        # Choose a default CPU model when cpu_mode is not specified
        if cpu.mode is None:
            caps.host.cpu.model = libvirt_utils.get_cpu_model_from_arch(
                caps.host.cpu.arch)
            caps.host.cpu.features = set()
            features = features.union(_resolve_features(caps.host.cpu))
        else:
            models = [self._get_cpu_model_mapping(model)
                      for model in CONF.libvirt.cpu_models]

            # Aarch64 platform doesn't return the default CPU models
            if caps.host.cpu.arch == fields.Architecture.AARCH64:
                if not models:
                    models = ['max']
            # For custom mode, iterate through cpu models
            for model in models:
                caps.host.cpu.model = model
                caps.host.cpu.features = set()
                features = features.union(_resolve_features(caps.host.cpu))
            # Account for features in cpu_model_extra_flags conf
            features = features.union([f.name for f in cpu.features])

        return libvirt_utils.cpu_features_to_traits(features)

    def _get_guest_baseline_cpu_features(self, xml_str):
        """Calls libvirt's baselineCPU API to compute the biggest set of
        CPU features which is compatible with the given host CPU.

        :param xml_str: XML description of host CPU
        :return: An XML string of the computed CPU, or None on error
        """
        LOG.debug("Libvirt baseline CPU %s", xml_str)
        # TODO(lei-zh): baselineCPU is not supported on all platforms.
        # There is some work going on in the libvirt community to replace the
        # baseline call. Consider using the new apis when they are ready. See
        # https://www.redhat.com/archives/libvir-list/2018-May/msg01204.html.
        try:
            if hasattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'):
                return self._host.get_connection().baselineCPU(
                    [xml_str],
                    libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)
            else:
                return self._host.get_connection().baselineCPU([xml_str])
        except libvirt.libvirtError as ex:
            with excutils.save_and_reraise_exception() as ctxt:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                    ctxt.reraise = False
                    LOG.debug('URI %(uri)s does not support full set'
                              ' of host capabilities: %(error)s',
                              {'uri': self._host._uri, 'error': ex})
                    return None
