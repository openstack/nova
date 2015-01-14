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

Supports KVM, LXC, QEMU, UML, and XEN.

"""

import collections
import contextlib
import errno
import functools
import glob
import mmap
import operator
import os
import random
import shutil
import sys
import tempfile
import time
import uuid
from xml.dom import minidom

import eventlet
from eventlet import greenthread
from eventlet import tpool
from lxml import etree
from oslo.config import cfg
from oslo.serialization import jsonutils
from oslo.utils import encodeutils
from oslo.utils import excutils
from oslo.utils import importutils
from oslo.utils import strutils
from oslo.utils import timeutils
from oslo.utils import units
from oslo_concurrency import processutils
import six

from nova.api.metadata import base as instance_metadata
from nova import block_device
from nova.compute import arch
from nova.compute import hv_type
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_mode
from nova.console import serial as serial_console
from nova.console import type as ctype
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova.i18n import _LE
from nova.i18n import _LI
from nova.i18n import _LW
from nova import image
from nova.network import model as network_model
from nova import objects
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.pci import manager as pci_manager
from nova.pci import utils as pci_utils
from nova import rpc
from nova import utils
from nova import version
from nova.virt import block_device as driver_block_device
from nova.virt import configdrive
from nova.virt import diagnostics
from nova.virt.disk import api as disk
from nova.virt.disk.vfs import guestfs
from nova.virt import driver
from nova.virt import firewall
from nova.virt import hardware
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import dmcrypt
from nova.virt.libvirt import firewall as libvirt_firewall
from nova.virt.libvirt import host
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import lvm
from nova.virt.libvirt import rbd_utils
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt.libvirt import vif as libvirt_vif
from nova.virt import netutils
from nova.virt import watchdog_actions
from nova import volume
from nova.volume import encryptors

libvirt = None

LOG = logging.getLogger(__name__)

libvirt_opts = [
    cfg.StrOpt('rescue_image_id',
               help='Rescue ami image. This will not be used if an image id '
                    'is provided by the user.'),
    cfg.StrOpt('rescue_kernel_id',
               help='Rescue aki image'),
    cfg.StrOpt('rescue_ramdisk_id',
               help='Rescue ari image'),
    cfg.StrOpt('virt_type',
               default='kvm',
               help='Libvirt domain type (valid options are: '
                    'kvm, lxc, qemu, uml, xen)'),
    cfg.StrOpt('connection_uri',
               default='',
               help='Override the default libvirt URI '
                    '(which is dependent on virt_type)'),
    cfg.BoolOpt('inject_password',
                default=False,
                help='Inject the admin password at boot time, '
                     'without an agent.'),
    cfg.BoolOpt('inject_key',
                default=False,
                help='Inject the ssh public key at boot time'),
    cfg.IntOpt('inject_partition',
                default=-2,
                help='The partition to inject to : '
                     '-2 => disable, -1 => inspect (libguestfs only), '
                     '0 => not partitioned, >0 => partition number'),
    cfg.BoolOpt('use_usb_tablet',
                default=True,
                help='Sync virtual and real mouse cursors in Windows VMs'),
    cfg.StrOpt('live_migration_uri',
               default="qemu+tcp://%s/system",
               help='Migration target URI '
                    '(any included "%s" is replaced with '
                    'the migration target hostname)'),
    cfg.StrOpt('live_migration_flag',
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER, '
                       'VIR_MIGRATE_LIVE, VIR_MIGRATE_TUNNELLED',
               help='Migration flags to be set for live migration'),
    cfg.StrOpt('block_migration_flag',
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER, '
                       'VIR_MIGRATE_LIVE, VIR_MIGRATE_TUNNELLED, '
                       'VIR_MIGRATE_NON_SHARED_INC',
               help='Migration flags to be set for block migration'),
    cfg.IntOpt('live_migration_bandwidth',
               default=0,
               help='Maximum bandwidth to be used during migration, in Mbps'),
    cfg.StrOpt('snapshot_image_format',
               help='Snapshot image format (valid options are : '
                    'raw, qcow2, vmdk, vdi). '
                    'Defaults to same as source image'),
    cfg.ListOpt('volume_drivers',
                default=[
                  'iscsi=nova.virt.libvirt.volume.LibvirtISCSIVolumeDriver',
                  'iser=nova.virt.libvirt.volume.LibvirtISERVolumeDriver',
                  'local=nova.virt.libvirt.volume.LibvirtVolumeDriver',
                  'fake=nova.virt.libvirt.volume.LibvirtFakeVolumeDriver',
                  'rbd=nova.virt.libvirt.volume.LibvirtNetVolumeDriver',
                  'sheepdog=nova.virt.libvirt.volume.LibvirtNetVolumeDriver',
                  'nfs=nova.virt.libvirt.volume.LibvirtNFSVolumeDriver',
                  'smbfs=nova.virt.libvirt.volume.LibvirtSMBFSVolumeDriver',
                  'aoe=nova.virt.libvirt.volume.LibvirtAOEVolumeDriver',
                  'glusterfs='
                      'nova.virt.libvirt.volume.LibvirtGlusterfsVolumeDriver',
                  'fibre_channel=nova.virt.libvirt.volume.'
                      'LibvirtFibreChannelVolumeDriver',
                  'scality='
                      'nova.virt.libvirt.volume.LibvirtScalityVolumeDriver',
                  'gpfs='
                      'nova.virt.libvirt.volume.LibvirtGPFSVolumeDriver',
                  ],
                help='DEPRECATED. Libvirt handlers for remote volumes. '
                     'This option is deprecated and will be removed in the '
                     'Kilo release.'),
    cfg.StrOpt('disk_prefix',
               help='Override the default disk prefix for the devices attached'
                    ' to a server, which is dependent on virt_type. '
                    '(valid options are: sd, xvd, uvd, vd)'),
    cfg.IntOpt('wait_soft_reboot_seconds',
               default=120,
               help='Number of seconds to wait for instance to shut down after'
                    ' soft reboot request is made. We fall back to hard reboot'
                    ' if instance does not shutdown within this window.'),
    cfg.StrOpt('cpu_mode',
               help='Set to "host-model" to clone the host CPU feature flags; '
                    'to "host-passthrough" to use the host CPU model exactly; '
                    'to "custom" to use a named CPU model; '
                    'to "none" to not set any CPU model. '
                    'If virt_type="kvm|qemu", it will default to '
                    '"host-model", otherwise it will default to "none"'),
    cfg.StrOpt('cpu_model',
               help='Set to a named libvirt CPU model (see names listed '
                    'in /usr/share/libvirt/cpu_map.xml). Only has effect if '
                    'cpu_mode="custom" and virt_type="kvm|qemu"'),
    cfg.StrOpt('snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where libvirt driver will store snapshots '
                    'before uploading them to image service'),
    cfg.StrOpt('xen_hvmloader_path',
                default='/usr/lib/xen/boot/hvmloader',
                help='Location where the Xen hvmloader is kept'),
    cfg.ListOpt('disk_cachemodes',
                 default=[],
                 help='Specific cachemodes to use for different disk types '
                      'e.g: file=directsync,block=none'),
    cfg.StrOpt('rng_dev_path',
                help='A path to a device that will be used as source of '
                     'entropy on the host. Permitted options are: '
                     '/dev/random or /dev/hwrng'),
    cfg.ListOpt('hw_machine_type',
               help='For qemu or KVM guests, set this option to specify '
                    'a default machine type per host architecture. '
                    'You can find a list of supported machine types '
                    'in your environment by checking the output of '
                    'the "virsh capabilities"command. The format of the '
                    'value for this config option is host-arch=machine-type. '
                    'For example: x86_64=machinetype1,armv7l=machinetype2'),
    cfg.StrOpt('sysinfo_serial',
               default='auto',
               help='The data source used to the populate the host "serial" '
                    'UUID exposed to guest in the virtual BIOS. Permitted '
                    'options are "hardware", "os", "none" or "auto" '
                    '(default).'),
    cfg.IntOpt('mem_stats_period_seconds',
                default=10,
                help='A number of seconds to memory usage statistics period. '
                     'Zero or negative value mean to disable memory usage '
                     'statistics.'),
    cfg.ListOpt('uid_maps',
                default=[],
                help='List of uid targets and ranges.'
                     'Syntax is guest-uid:host-uid:count'
                     'Maximum of 5 allowed.'),
    cfg.ListOpt('gid_maps',
                default=[],
                help='List of guid targets and ranges.'
                     'Syntax is guest-gid:host-gid:count'
                     'Maximum of 5 allowed.')
    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts, 'libvirt')
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('enabled', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('cipher', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('key_size', 'nova.compute.api',
                group='ephemeral_storage_encryption')
CONF.import_opt('live_migration_retry_count', 'nova.compute.manager')
CONF.import_opt('vncserver_proxyclient_address', 'nova.vnc')
CONF.import_opt('server_proxyclient_address', 'nova.spice', group='spice')
CONF.import_opt('vcpu_pin_set', 'nova.virt.hardware')
CONF.import_opt('vif_plugging_is_fatal', 'nova.virt.driver')
CONF.import_opt('vif_plugging_timeout', 'nova.virt.driver')
CONF.import_opt('enabled', 'nova.console.serial', group='serial_console')
CONF.import_opt('proxyclient_address', 'nova.console.serial',
                group='serial_console')
CONF.import_opt('hw_disk_discard', 'nova.virt.libvirt.imagebackend',
                group='libvirt')

DEFAULT_FIREWALL_DRIVER = "%s.%s" % (
    libvirt_firewall.__name__,
    libvirt_firewall.IptablesFirewallDriver.__name__)

MAX_CONSOLE_BYTES = 100 * units.Ki

# The libvirt driver will prefix any disable reason codes with this string.
DISABLE_PREFIX = 'AUTO: '
# Disable reason for the service which was enabled or disabled without reason
DISABLE_REASON_UNDEFINED = 'None'

# Guest config console string
CONSOLE = "console=tty0 console=ttyS0"

GuestNumaConfig = collections.namedtuple(
    'GuestNumaConfig', ['cpuset', 'cputune', 'numaconfig', 'numatune'])


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
    # NOTE(maoy): The DOMAIN_BLOCKED state is only valid in Xen.
    # It means that the VM is running and the vCPU is idle. So,
    # we map it to RUNNING
    VIR_DOMAIN_BLOCKED: power_state.RUNNING,
    VIR_DOMAIN_PAUSED: power_state.PAUSED,
    # NOTE(maoy): The libvirt API doc says that DOMAIN_SHUTDOWN
    # means the domain is being shut down. So technically the domain
    # is still running. SHUTOFF is the real powered off state.
    # But we will map both to SHUTDOWN anyway.
    # http://libvirt.org/html/libvirt-libvirt.html
    VIR_DOMAIN_SHUTDOWN: power_state.SHUTDOWN,
    VIR_DOMAIN_SHUTOFF: power_state.SHUTDOWN,
    VIR_DOMAIN_CRASHED: power_state.CRASHED,
    VIR_DOMAIN_PMSUSPENDED: power_state.SUSPENDED,
}

MIN_LIBVIRT_VERSION = (0, 9, 11)
# When the above version matches/exceeds this version
# delete it & corresponding code using it
MIN_LIBVIRT_DEVICE_CALLBACK_VERSION = (1, 1, 1)
# Live snapshot requirements
REQ_HYPERVISOR_LIVESNAPSHOT = "QEMU"
# TODO(sdague): this should be 1.0.0, but hacked to set 1.3.0 until
# https://bugs.launchpad.net/nova/+bug/1334398
# can be diagnosed & resolved
MIN_LIBVIRT_LIVESNAPSHOT_VERSION = (1, 3, 0)
MIN_QEMU_LIVESNAPSHOT_VERSION = (1, 3, 0)
# block size tuning requirements
MIN_LIBVIRT_BLOCKIO_VERSION = (0, 10, 2)
# BlockJobInfo management requirement
MIN_LIBVIRT_BLOCKJOBINFO_VERSION = (1, 1, 1)
# Relative block commit (feature is detected,
# this version is only used for messaging)
MIN_LIBVIRT_BLOCKCOMMIT_RELATIVE_VERSION = (1, 2, 7)
# libvirt discard feature
MIN_LIBVIRT_DISCARD_VERSION = (1, 0, 6)
MIN_QEMU_DISCARD_VERSION = (1, 6, 0)
REQ_HYPERVISOR_DISCARD = "QEMU"
# libvirt numa topology support
MIN_LIBVIRT_NUMA_TOPOLOGY_VERSION = (1, 0, 4)
# fsFreeze/fsThaw requirement
MIN_LIBVIRT_FSFREEZE_VERSION = (1, 2, 5)

# Hyper-V paravirtualized time source
MIN_LIBVIRT_HYPERV_TIMER_VERSION = (1, 2, 2)
MIN_QEMU_HYPERV_TIMER_VERSION = (2, 0, 0)

MIN_LIBVIRT_HYPERV_FEATURE_VERSION = (1, 0, 0)
MIN_LIBVIRT_HYPERV_FEATURE_EXTRA_VERSION = (1, 1, 0)
MIN_QEMU_HYPERV_FEATURE_VERSION = (1, 1, 0)


class LibvirtDriver(driver.ComputeDriver):

    capabilities = {
        "has_imagecache": True,
        "supports_recreate": True,
        }

    def __init__(self, virtapi, read_only=False):
        super(LibvirtDriver, self).__init__(virtapi)

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')

        self._host = host.Host(self.uri(), read_only,
                               lifecycle_event_handler=self.emit_event,
                               conn_event_handler=self._handle_conn_event)
        self._skip_list_all_domains = False
        self._initiator = None
        self._fc_wwnns = None
        self._fc_wwpns = None
        self._caps = None
        self._vcpu_total = 0
        self.firewall_driver = firewall.load_driver(
            DEFAULT_FIREWALL_DRIVER,
            self.virtapi,
            host=self._host)

        self.vif_driver = libvirt_vif.LibvirtGenericVIFDriver()

        self.volume_drivers = driver.driver_dict_from_config(
            CONF.libvirt.volume_drivers, self)

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
                LOG.warn(_LW('Invalid cachemode %(cache_mode)s specified '
                             'for disk type %(disk_type)s.'),
                         {'cache_mode': cache_mode, 'disk_type': disk_type})
                continue
            self.disk_cachemodes[disk_type] = cache_mode

        self._volume_api = volume.API()
        self._image_api = image.API()
        self._events_delayed = {}
        # Note(toabctl): During a reboot of a Xen domain, STOPPED and
        #                STARTED events are sent. To prevent shutting
        #                down the domain during a reboot, delay the
        #                STOPPED lifecycle event some seconds.
        if CONF.libvirt.virt_type == "xen":
            self._lifecycle_delay = 15
        else:
            self._lifecycle_delay = 0

        sysinfo_serial_funcs = {
            'none': lambda: None,
            'hardware': self._get_host_sysinfo_serial_hardware,
            'os': self._get_host_sysinfo_serial_os,
            'auto': self._get_host_sysinfo_serial_auto,
        }

        self._sysinfo_serial_func = sysinfo_serial_funcs.get(
            CONF.libvirt.sysinfo_serial)
        if not self._sysinfo_serial_func:
            raise exception.NovaException(
                _("Unexpected sysinfo_serial setting '%(actual)s'. "
                  "Permitted values are %(expect)s'") %
                  {'actual': CONF.libvirt.sysinfo_serial,
                   'expect': ', '.join("'%s'" % k for k in
                                       sysinfo_serial_funcs.keys())})

    @property
    def disk_cachemode(self):
        if self._disk_cachemode is None:
            # We prefer 'none' for consistent performance, host crash
            # safety & migration correctness by avoiding host page cache.
            # Some filesystems (eg GlusterFS via FUSE) don't support
            # O_DIRECT though. For those we fallback to 'writethrough'
            # which gives host crash safety, and is safe for migration
            # provided the filesystem is cache coherent (cluster filesystems
            # typically are, but things like NFS are not).
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
        caps = self._get_host_capabilities()
        hostarch = caps.host.cpu.arch
        if (CONF.libvirt.virt_type not in ('qemu', 'kvm') or
            hostarch not in (arch.I686, arch.X86_64)):
            LOG.warn(_LW('The libvirt driver is not tested on '
                         '%(type)s/%(arch)s by the OpenStack project and '
                         'thus its quality can not be ensured. For more '
                         'information, see: https://wiki.openstack.org/wiki/'
                         'HypervisorSupportMatrix'),
                        {'type': CONF.libvirt.virt_type, 'arch': hostarch})

    def _handle_conn_event(self, enabled, reason):
        LOG.info(_LI("Connection event '%(enabled)d' reason '%(reason)s'"),
                 {'enabled': enabled, 'reason': reason})
        if reason is None:
            reason = DISABLE_REASON_UNDEFINED
        self._set_host_enabled(enabled, reason)

    def init_host(self, host):
        self._host.initialize()

        self._do_quality_warnings()

        if (CONF.libvirt.virt_type == 'lxc' and
                not (CONF.libvirt.uid_maps and CONF.libvirt.gid_maps)):
            LOG.warn(_LW("Running libvirt-lxc without user namespaces is "
                         "dangerous. Containers spawned by Nova will be run "
                         "as the host's root user. It is highly suggested "
                         "that user namespaces be used in a public or "
                         "multi-tenant environment."))

        # Stop libguestfs using KVM unless we're also configured
        # to use this. This solves problem where people need to
        # stop Nova use of KVM because nested-virt is broken
        if CONF.libvirt.virt_type != "kvm":
            guestfs.force_tcg()

        if not self._host.has_min_version(MIN_LIBVIRT_VERSION):
            major = MIN_LIBVIRT_VERSION[0]
            minor = MIN_LIBVIRT_VERSION[1]
            micro = MIN_LIBVIRT_VERSION[2]
            raise exception.NovaException(
                _('Nova requires libvirt version '
                  '%(major)i.%(minor)i.%(micro)i or greater.') %
                {'major': major, 'minor': minor, 'micro': micro})

    def _get_connection(self):
        try:
            conn = self._host.get_connection()
        except libvirt.libvirtError as ex:
            LOG.exception(_LE("Connection to libvirt failed: %s"), ex)
            payload = dict(ip=LibvirtDriver.get_host_ip_addr(),
                           method='_connect',
                           reason=ex)
            rpc.get_notifier('compute').error(nova_context.get_admin_context(),
                                              'compute.libvirt.error',
                                              payload)
            raise exception.HypervisorUnavailable(host=CONF.host)

        return conn

    _conn = property(_get_connection)

    @staticmethod
    def uri():
        if CONF.libvirt.virt_type == 'uml':
            uri = CONF.libvirt.connection_uri or 'uml:///system'
        elif CONF.libvirt.virt_type == 'xen':
            uri = CONF.libvirt.connection_uri or 'xen:///'
        elif CONF.libvirt.virt_type == 'lxc':
            uri = CONF.libvirt.connection_uri or 'lxc:///'
        else:
            uri = CONF.libvirt.connection_uri or 'qemu:///system'
        return uri

    def instance_exists(self, instance):
        """Efficient override of base instance_exists method."""
        try:
            self._get_domain(instance)
            return True
        except exception.NovaException:
            return False

    def _list_instance_domains_fast(self, only_running=True):
        # The modern (>= 0.9.13) fast way - 1 single API call for all domains
        flags = libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE
        if not only_running:
            flags = flags | libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE
        return self._conn.listAllDomains(flags)

    def _list_instance_domains_slow(self, only_running=True):
        # The legacy (< 0.9.13) slow way - O(n) API call for n domains
        uuids = []
        doms = []
        # Redundant numOfDomains check is for libvirt bz #836647
        if self._conn.numOfDomains() > 0:
            for id in self._conn.listDomainsID():
                try:
                    dom = self._lookup_by_id(id)
                    doms.append(dom)
                    uuids.append(dom.UUIDString())
                except exception.InstanceNotFound:
                    continue

        if only_running:
            return doms

        for name in self._conn.listDefinedDomains():
            try:
                dom = self._lookup_by_name(name)
                if dom.UUIDString() not in uuids:
                    doms.append(dom)
            except exception.InstanceNotFound:
                continue

        return doms

    def _list_instance_domains(self, only_running=True, only_guests=True):
        """Get a list of libvirt.Domain objects for nova instances

        :param only_running: True to only return running instances
        :param only_guests: True to filter out any host domain (eg Dom-0)

        Query libvirt to a get a list of all libvirt.Domain objects
        that correspond to nova instances. If the only_running parameter
        is true this list will only include active domains, otherwise
        inactive domains will be included too. If the only_guests parameter
        is true the list will have any "host" domain (aka Xen Domain-0)
        filtered out.

        :returns: list of libvirt.Domain objects
        """

        if not self._skip_list_all_domains:
            try:
                alldoms = self._list_instance_domains_fast(only_running)
            except (libvirt.libvirtError, AttributeError) as ex:
                LOG.info(_LI("Unable to use bulk domain list APIs, "
                             "falling back to slow code path: %(ex)s"),
                         {'ex': ex})
                self._skip_list_all_domains = True

        if self._skip_list_all_domains:
            # Old libvirt, or a libvirt driver which doesn't
            # implement the new API
            alldoms = self._list_instance_domains_slow(only_running)

        doms = []
        for dom in alldoms:
            if only_guests and dom.ID() == 0:
                continue
            doms.append(dom)

        return doms

    def list_instances(self):
        names = []
        for dom in self._list_instance_domains(only_running=False):
            names.append(dom.name())

        return names

    def list_instance_uuids(self):
        uuids = []
        for dom in self._list_instance_domains(only_running=False):
            uuids.append(dom.UUIDString())

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
        disk.teardown_container(container_dir, rootfs_dev)

    def _destroy(self, instance):
        try:
            virt_dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            virt_dom = None

        # If the instance is already terminated, we're still happy
        # Otherwise, destroy it
        old_domid = -1
        if virt_dom is not None:
            try:
                old_domid = virt_dom.ID()
                virt_dom.destroy()

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
                    state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
                    if state == power_state.SHUTDOWN:
                        is_okay = True
                elif errcode == libvirt.VIR_ERR_OPERATION_TIMEOUT:
                    LOG.warn(_LW("Cannot destroy instance, operation time "
                                 "out"),
                            instance=instance)
                    reason = _("operation time out")
                    raise exception.InstancePowerOffFailure(reason=reason)

                if not is_okay:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE('Error from libvirt during destroy. '
                                      'Code=%(errcode)s Error=%(e)s'),
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
                LOG.warning(_LW("During wait destroy, instance disappeared."),
                            instance=instance)
                raise loopingcall.LoopingCallDone()

            if state == power_state.SHUTDOWN:
                LOG.info(_LI("Instance destroyed successfully."),
                         instance=instance)
                raise loopingcall.LoopingCallDone()

            # NOTE(wangpan): If the instance was booted again after destroy,
            #                this may be a endless loop, so check the id of
            #                domain here, if it changed and the instance is
            #                still running, we should destroy it again.
            # see https://bugs.launchpad.net/nova/+bug/1111213 for more details
            if new_domid != expected_domid:
                LOG.info(_LI("Instance may be started again."),
                         instance=instance)
                kwargs['is_running'] = True
                raise loopingcall.LoopingCallDone()

        kwargs = {'is_running': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_destroy,
                                                     old_domid)
        timer.start(interval=0.5).wait()
        if kwargs['is_running']:
            LOG.info(_LI("Going to destroy instance again."),
                     instance=instance)
            self._destroy(instance)
        else:
            # NOTE(GuanQiang): teardown container to avoid resource leak
            if CONF.libvirt.virt_type == 'lxc':
                self._teardown_container(instance)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        self._destroy(instance)
        self.cleanup(context, instance, network_info, block_device_info,
                     destroy_disks, migrate_data)

    def _undefine_domain(self, instance):
        try:
            virt_dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            virt_dom = None
        if virt_dom:
            try:
                try:
                    virt_dom.undefineFlags(
                        libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
                except libvirt.libvirtError:
                    LOG.debug("Error from libvirt during undefineFlags."
                        " Retrying with undefine", instance=instance)
                    virt_dom.undefine()
                except AttributeError:
                    # NOTE(vish): Older versions of libvirt don't support
                    #             undefine flags, so attempt to do the
                    #             right thing.
                    try:
                        if virt_dom.hasManagedSaveImage(0):
                            virt_dom.managedSaveRemove(0)
                    except AttributeError:
                        pass
                    virt_dom.undefine()
            except libvirt.libvirtError as e:
                with excutils.save_and_reraise_exception():
                    errcode = e.get_error_code()
                    LOG.error(_LE('Error from libvirt during undefine. '
                                  'Code=%(errcode)s Error=%(e)s'),
                              {'errcode': errcode, 'e': e}, instance=instance)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        if destroy_vifs:
            self._unplug_vifs(instance, network_info, True)

        retry = True
        while retry:
            try:
                self.firewall_driver.unfilter_instance(instance,
                                                    network_info=network_info)
            except libvirt.libvirtError as e:
                try:
                    state = self.get_info(instance).state
                except exception.InstanceNotFound:
                    state = power_state.SHUTDOWN

                if state != power_state.SHUTDOWN:
                    LOG.warn(_LW("Instance may be still running, destroy "
                                 "it again."), instance=instance)
                    self._destroy(instance)
                else:
                    retry = False
                    errcode = e.get_error_code()
                    LOG.exception(_LE('Error from libvirt during unfilter. '
                                      'Code=%(errcode)s Error=%(e)s'),
                                  {'errcode': errcode, 'e': e},
                                  instance=instance)
                    reason = "Error unfiltering instance."
                    raise exception.InstanceTerminationFailure(reason=reason)
            except Exception:
                retry = False
                raise
            else:
                retry = False

        # FIXME(wangpan): if the instance is booted again here, such as the
        #                 the soft reboot operation boot it here, it will
        #                 become "running deleted", should we check and destroy
        #                 it at the end of this method?

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
                    encryptor.detach_volume(**encryption)

            try:
                self._disconnect_volume(connection_info, disk_dev)
            except Exception as exc:
                with excutils.save_and_reraise_exception() as ctxt:
                    if destroy_disks:
                        # Don't block on Volume errors if we're trying to
                        # delete the instance as we may be partially created
                        # or deleted
                        ctxt.reraise = False
                        LOG.warn(_LW("Ignoring Volume Error on vol %(vol_id)s "
                                     "during delete %(exc)s"),
                                 {'vol_id': vol.get('volume_id'), 'exc': exc},
                                 instance=instance)

        if destroy_disks:
            # NOTE(haomai): destroy volumes if needed
            if CONF.libvirt.images_type == 'lvm':
                self._cleanup_lvm(instance)
            if CONF.libvirt.images_type == 'rbd':
                self._cleanup_rbd(instance)

        if destroy_disks or (
                migrate_data and migrate_data.get('is_shared_block_storage',
                                                  False)):
            self._delete_instance_files(instance)

        if CONF.serial_console.enabled:
            serials = self._get_serial_ports_from_instance(instance)
            for hostname, port in serials:
                serial_console.release_port(host=hostname, port=port)

        self._undefine_domain(instance)

    def _detach_encrypted_volumes(self, instance):
        """Detaches encrypted volumes attached to instance."""
        disks = jsonutils.loads(self.get_instance_disk_info(instance))
        encrypted_volumes = filter(dmcrypt.is_encrypted,
                                   [disk['path'] for disk in disks])
        for path in encrypted_volumes:
            dmcrypt.delete_volume(path)

    def _get_serial_ports_from_instance(self, instance, mode=None):
        """Returns an iterator over serial port(s) configured on instance.

        :param mode: Should be a value in (None, bind, connect)
        """
        virt_dom = self._get_domain(instance)
        xml = virt_dom.XMLDesc(0)
        tree = etree.fromstring(xml)
        for serial in tree.findall("./devices/serial"):
            if serial.get("type") == "tcp":
                source = serial.find("./source")
                if source is not None:
                    if mode and source.get("mode") != mode:
                        continue
                    yield (source.get("host"), int(source.get("service")))

    @staticmethod
    def _get_rbd_driver():
        return rbd_utils.RBDDriver(
                pool=CONF.libvirt.images_rbd_pool,
                ceph_conf=CONF.libvirt.images_rbd_ceph_conf,
                rbd_user=CONF.libvirt.rbd_user)

    def _cleanup_rbd(self, instance):
        LibvirtDriver._get_rbd_driver().cleanup_volumes(instance)

    def _cleanup_lvm(self, instance):
        """Delete all LVM disks for given instance object."""
        if instance.get('ephemeral_key_uuid') is not None:
            self._detach_encrypted_volumes(instance)

        disks = self._lvm_disks(instance)
        if disks:
            lvm.remove_volumes(disks)

    def _lvm_disks(self, instance):
        """Returns all LVM disks for given instance object."""
        if CONF.libvirt.images_volume_group:
            vg = os.path.join('/dev', CONF.libvirt.images_volume_group)
            if not os.path.exists(vg):
                return []
            pattern = '%s_' % instance['uuid']

            def belongs_to_instance(disk):
                return disk.startswith(pattern)

            def fullpath(name):
                return os.path.join(vg, name)

            logical_volumes = lvm.list_volumes(vg)

            disk_names = filter(belongs_to_instance, logical_volumes)
            disks = map(fullpath, disk_names)
            return disks
        return []

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = libvirt_utils.get_iscsi_initiator()
            if not self._initiator:
                LOG.debug('Could not determine iscsi initiator name',
                          instance=instance)

        if not self._fc_wwnns:
            self._fc_wwnns = libvirt_utils.get_fc_wwnns()
            if not self._fc_wwnns or len(self._fc_wwnns) == 0:
                LOG.debug('Could not determine fibre channel '
                          'world wide node names',
                          instance=instance)

        if not self._fc_wwpns:
            self._fc_wwpns = libvirt_utils.get_fc_wwpns()
            if not self._fc_wwpns or len(self._fc_wwpns) == 0:
                LOG.debug('Could not determine fibre channel '
                          'world wide port names',
                          instance=instance)

        connector = {'ip': CONF.my_block_storage_ip,
                     'host': CONF.host}

        if self._initiator:
            connector['initiator'] = self._initiator

        if self._fc_wwnns and self._fc_wwpns:
            connector["wwnns"] = self._fc_wwnns
            connector["wwpns"] = self._fc_wwpns

        return connector

    def _cleanup_resize(self, instance, network_info):
        # NOTE(wangpan): we get the pre-grizzly instance path firstly,
        #                so the backup dir of pre-grizzly instance can
        #                be deleted correctly with grizzly or later nova.
        pre_grizzly_name = libvirt_utils.get_instance_path(instance,
                                                           forceold=True)
        target = pre_grizzly_name + '_resize'
        if not os.path.exists(target):
            target = libvirt_utils.get_instance_path(instance) + '_resize'

        if os.path.exists(target):
            # Deletion can fail over NFS, so retry the deletion as required.
            # Set maximum attempt as 5, most test can remove the directory
            # for the second time.
            utils.execute('rm', '-rf', target, delay_on_retry=True,
                          attempts=5)

        if instance['host'] != CONF.host:
            self._undefine_domain(instance)
            self.unplug_vifs(instance, network_info)
            self.firewall_driver.unfilter_instance(instance, network_info)

    def _connect_volume(self, connection_info, disk_info):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        driver.connect_volume(connection_info, disk_info)

    def _disconnect_volume(self, connection_info, disk_dev):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        return driver.disconnect_volume(connection_info, disk_dev)

    def _get_volume_config(self, connection_info, disk_info):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        return driver.get_config(connection_info, disk_info)

    def _get_volume_encryptor(self, connection_info, encryption):
        encryptor = encryptors.get_volume_encryptor(connection_info,
                                                    **encryption)
        return encryptor

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        virt_dom = self._get_domain(instance)
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

            if not self._host.has_min_version(MIN_LIBVIRT_BLOCKIO_VERSION):
                ver = ".".join([str(x) for x in MIN_LIBVIRT_BLOCKIO_VERSION])
                msg = _("Volume sets block size, but libvirt '%s' or later is "
                        "required.") % ver
                raise exception.Invalid(msg)

        disk_info = blockinfo.get_info_from_bdm(CONF.libvirt.virt_type, bdm)
        self._connect_volume(connection_info, disk_info)
        conf = self._get_volume_config(connection_info, disk_info)
        self._set_cache_mode(conf)

        try:
            # NOTE(vish): We can always affect config because our
            #             domains are persistent, but we should only
            #             affect live if the domain is running.
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
            if state in (power_state.RUNNING, power_state.PAUSED):
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE

            if encryption:
                encryptor = self._get_volume_encryptor(connection_info,
                                                       encryption)
                encryptor.attach_volume(context, **encryption)

            virt_dom.attachDeviceFlags(conf.to_xml(), flags)
        except Exception as ex:
            LOG.exception(_LE('Failed to attach volume at mountpoint: %s'),
                          mountpoint, instance=instance)
            if isinstance(ex, libvirt.libvirtError):
                errcode = ex.get_error_code()
                if errcode == libvirt.VIR_ERR_OPERATION_FAILED:
                    self._disconnect_volume(connection_info, disk_dev)
                    raise exception.DeviceIsBusy(device=disk_dev)

            with excutils.save_and_reraise_exception():
                self._disconnect_volume(connection_info, disk_dev)

    def _swap_volume(self, domain, disk_path, new_path, resize_to):
        """Swap existing disk with a new block device."""
        # Save a copy of the domain's persistent XML file
        xml = domain.XMLDesc(
            libvirt.VIR_DOMAIN_XML_INACTIVE |
            libvirt.VIR_DOMAIN_XML_SECURE)

        # Abort is an idempotent operation, so make sure any block
        # jobs which may have failed are ended.
        try:
            domain.blockJobAbort(disk_path, 0)
        except Exception:
            pass

        try:
            # NOTE (rmk): blockRebase cannot be executed on persistent
            #             domains, so we need to temporarily undefine it.
            #             If any part of this block fails, the domain is
            #             re-defined regardless.
            if domain.isPersistent():
                domain.undefine()

            # Start copy with VIR_DOMAIN_REBASE_REUSE_EXT flag to
            # allow writing to existing external volume file
            domain.blockRebase(disk_path, new_path, 0,
                               libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY |
                               libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT)

            while self._wait_for_block_job(domain, disk_path):
                time.sleep(0.5)

            domain.blockJobAbort(disk_path,
                                 libvirt.VIR_DOMAIN_BLOCK_JOB_ABORT_PIVOT)
            if resize_to:
                # NOTE(alex_xu): domain.blockJobAbort isn't sync call. This
                # is bug in libvirt. So we need waiting for the pivot is
                # finished. libvirt bug #1119173
                while self._wait_for_block_job(domain, disk_path,
                                               wait_for_job_clean=True):
                    time.sleep(0.5)
                domain.blockResize(disk_path, resize_to * units.Gi / units.Ki)
        finally:
            self._conn.defineXML(xml)

    def swap_volume(self, old_connection_info,
                    new_connection_info, instance, mountpoint, resize_to):
        virt_dom = self._get_domain(instance)
        disk_dev = mountpoint.rpartition("/")[2]
        xml = self._get_disk_xml(virt_dom.XMLDesc(0), disk_dev)
        if not xml:
            raise exception.DiskNotFound(location=disk_dev)
        disk_info = {
            'dev': disk_dev,
            'bus': blockinfo.get_disk_bus_for_disk_dev(
                CONF.libvirt.virt_type, disk_dev),
            'type': 'disk',
            }
        self._connect_volume(new_connection_info, disk_info)
        conf = self._get_volume_config(new_connection_info, disk_info)
        if not conf.source_path:
            self._disconnect_volume(new_connection_info, disk_dev)
            raise NotImplementedError(_("Swap only supports host devices"))

        self._swap_volume(virt_dom, disk_dev, conf.source_path, resize_to)
        self._disconnect_volume(old_connection_info, disk_dev)

    @staticmethod
    def _get_disk_xml(xml, device):
        """Returns the xml for the disk mounted at device."""
        try:
            doc = etree.fromstring(xml)
        except Exception:
            return None
        ret = doc.findall('./devices/disk')
        for node in ret:
            for child in node.getchildren():
                if child.tag == 'target':
                    if child.get('dev') == device:
                        return etree.tostring(node)

    def _get_existing_domain_xml(self, instance, network_info,
                                 block_device_info=None):
        try:
            virt_dom = self._get_domain(instance)
            xml = virt_dom.XMLDesc(0)
        except exception.InstanceNotFound:
            disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                                instance,
                                                block_device_info)
            xml = self._get_guest_xml(nova_context.get_admin_context(),
                                      instance, network_info, disk_info,
                                      block_device_info=block_device_info)
        return xml

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        disk_dev = mountpoint.rpartition("/")[2]
        try:
            virt_dom = self._get_domain(instance)
            xml = self._get_disk_xml(virt_dom.XMLDesc(0), disk_dev)
            if not xml:
                raise exception.DiskNotFound(location=disk_dev)
            else:
                # NOTE(vish): We can always affect config because our
                #             domains are persistent, but we should only
                #             affect live if the domain is running.
                flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
                state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
                if state in (power_state.RUNNING, power_state.PAUSED):
                    flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
                virt_dom.detachDeviceFlags(xml, flags)

                if encryption:
                    # The volume must be detached from the VM before
                    # disconnecting it from its encryptor. Otherwise, the
                    # encryptor may report that the volume is still in use.
                    encryptor = self._get_volume_encryptor(connection_info,
                                                           encryption)
                    encryptor.detach_volume(**encryption)
        except exception.InstanceNotFound:
            # NOTE(zhaoqin): If the instance does not exist, _lookup_by_name()
            #                will throw InstanceNotFound exception. Need to
            #                disconnect volume under this circumstance.
            LOG.warn(_LW("During detach_volume, instance disappeared."))
        except libvirt.libvirtError as ex:
            # NOTE(vish): This is called to cleanup volumes after live
            #             migration, so we should still disconnect even if
            #             the instance doesn't exist here anymore.
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                # NOTE(vish):
                LOG.warn(_LW("During detach_volume, instance disappeared."))
            else:
                raise

        self._disconnect_volume(connection_info, disk_dev)

    def attach_interface(self, instance, image_meta, vif):
        virt_dom = self._get_domain(instance)
        flavor = objects.Flavor.get_by_id(
            nova_context.get_admin_context(read_deleted='yes'),
            instance['instance_type_id'])
        self.vif_driver.plug(instance, vif)
        self.firewall_driver.setup_basic_filtering(instance, [vif])
        cfg = self.vif_driver.get_config(instance, vif, image_meta,
                                         flavor, CONF.libvirt.virt_type)
        try:
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
            if state == power_state.RUNNING or state == power_state.PAUSED:
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
            virt_dom.attachDeviceFlags(cfg.to_xml(), flags)
        except libvirt.libvirtError:
            LOG.error(_LE('attaching network adapter failed.'),
                     instance=instance, exc_info=True)
            self.vif_driver.unplug(instance, vif)
            raise exception.InterfaceAttachFailed(
                    instance_uuid=instance['uuid'])

    def detach_interface(self, instance, vif):
        virt_dom = self._get_domain(instance)
        flavor = objects.Flavor.get_by_id(
            nova_context.get_admin_context(read_deleted='yes'),
            instance['instance_type_id'])
        cfg = self.vif_driver.get_config(instance, vif, None, flavor,
                                         CONF.libvirt.virt_type)
        try:
            self.vif_driver.unplug(instance, vif)
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
            if state == power_state.RUNNING or state == power_state.PAUSED:
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
            virt_dom.detachDeviceFlags(cfg.to_xml(), flags)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                LOG.warn(_LW("During detach_interface, "
                             "instance disappeared."),
                         instance=instance)
            else:
                LOG.error(_LE('detaching network adapter failed.'),
                         instance=instance, exc_info=True)
                raise exception.InterfaceDetachFailed(
                        instance_uuid=instance['uuid'])

    def _create_snapshot_metadata(self, base, instance, img_fmt, snp_name):
        metadata = {'is_public': False,
                    'status': 'active',
                    'name': snp_name,
                    'properties': {
                                   'kernel_id': instance['kernel_id'],
                                   'image_location': 'snapshot',
                                   'image_state': 'available',
                                   'owner_id': instance['project_id'],
                                   'ramdisk_id': instance['ramdisk_id'],
                                   }
                    }
        if instance['os_type']:
            metadata['properties']['os_type'] = instance['os_type']

        # NOTE(vish): glance forces ami disk format to be ami
        if base.get('disk_format') == 'ami':
            metadata['disk_format'] = 'ami'
        else:
            metadata['disk_format'] = img_fmt

        metadata['container_format'] = base.get('container_format', 'bare')

        return metadata

    def snapshot(self, context, instance, image_id, update_task_state):
        """Create snapshot from a running VM instance.

        This command only works with qemu 0.14+
        """
        try:
            virt_dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance['uuid'])

        base_image_ref = instance['image_ref']

        base = compute_utils.get_image_metadata(
            context, self._image_api, base_image_ref, instance)

        snapshot = self._image_api.get(context, image_id)

        disk_path = libvirt_utils.find_disk(virt_dom)
        source_format = libvirt_utils.get_disk_type(disk_path)

        image_format = CONF.libvirt.snapshot_image_format or source_format

        # NOTE(bfilippov): save lvm and rbd as raw
        if image_format == 'lvm' or image_format == 'rbd':
            image_format = 'raw'

        metadata = self._create_snapshot_metadata(base,
                                                  instance,
                                                  image_format,
                                                  snapshot['name'])

        snapshot_name = uuid.uuid4().hex

        state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]

        # NOTE(rmk): Live snapshots require QEMU 1.3 and Libvirt 1.0.0.
        #            These restrictions can be relaxed as other configurations
        #            can be validated.
        # NOTE(dgenin): Instances with LVM encrypted ephemeral storage require
        #               cold snapshots. Currently, checking for encryption is
        #               redundant because LVM supports only cold snapshots.
        #               It is necessary in case this situation changes in the
        #               future.
        if (self._host.has_min_version(MIN_LIBVIRT_LIVESNAPSHOT_VERSION,
                                       MIN_QEMU_LIVESNAPSHOT_VERSION,
                                       REQ_HYPERVISOR_LIVESNAPSHOT)
             and source_format not in ('lvm', 'rbd')
             and not CONF.ephemeral_storage_encryption.enabled):
            live_snapshot = True
            # Abort is an idempotent operation, so make sure any block
            # jobs which may have failed are ended. This operation also
            # confirms the running instance, as opposed to the system as a
            # whole, has a new enough version of the hypervisor (bug 1193146).
            try:
                virt_dom.blockJobAbort(disk_path, 0)
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

        # NOTE(dkang): managedSave does not work for LXC
        if CONF.libvirt.virt_type != 'lxc' and not live_snapshot:
            if state == power_state.RUNNING or state == power_state.PAUSED:
                self._detach_pci_devices(virt_dom,
                    pci_manager.get_instance_pci_devs(instance))
                self._detach_sriov_ports(instance, virt_dom)
                virt_dom.managedSave(0)

        snapshot_backend = self.image_backend.snapshot(instance,
                disk_path,
                image_type=source_format)

        if live_snapshot:
            LOG.info(_LI("Beginning live snapshot process"),
                     instance=instance)
        else:
            LOG.info(_LI("Beginning cold snapshot process"),
                     instance=instance)

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
        snapshot_directory = CONF.libvirt.snapshots_directory
        fileutils.ensure_tree(snapshot_directory)
        with utils.tempdir(dir=snapshot_directory) as tmpdir:
            try:
                out_path = os.path.join(tmpdir, snapshot_name)
                if live_snapshot:
                    # NOTE(xqueralt): libvirt needs o+x in the temp directory
                    os.chmod(tmpdir, 0o701)
                    self._live_snapshot(context, instance, virt_dom, disk_path,
                                        out_path, image_format, base)
                else:
                    snapshot_backend.snapshot_extract(out_path, image_format)
            finally:
                new_dom = None
                # NOTE(dkang): because previous managedSave is not called
                #              for LXC, _create_domain must not be called.
                if CONF.libvirt.virt_type != 'lxc' and not live_snapshot:
                    if state == power_state.RUNNING:
                        new_dom = self._create_domain(domain=virt_dom)
                    elif state == power_state.PAUSED:
                        new_dom = self._create_domain(domain=virt_dom,
                                launch_flags=libvirt.VIR_DOMAIN_START_PAUSED)
                    if new_dom is not None:
                        self._attach_pci_devices(new_dom,
                            pci_manager.get_instance_pci_devs(instance))
                        self._attach_sriov_ports(context, instance, new_dom)
                LOG.info(_LI("Snapshot extracted, beginning image upload"),
                         instance=instance)

            # Upload that image to the image service

            update_task_state(task_state=task_states.IMAGE_UPLOADING,
                     expected_state=task_states.IMAGE_PENDING_UPLOAD)
            with libvirt_utils.file_open(out_path) as image_file:
                self._image_api.update(context,
                                       image_id,
                                       metadata,
                                       image_file)
                LOG.info(_LI("Snapshot image upload complete"),
                         instance=instance)

    @staticmethod
    def _wait_for_block_job(domain, disk_path, abort_on_error=False,
                            wait_for_job_clean=False):
        """Wait for libvirt block job to complete.

        Libvirt may return either cur==end or an empty dict when
        the job is complete, depending on whether the job has been
        cleaned up by libvirt yet, or not.

        :returns: True if still in progress
                  False if completed
        """

        status = domain.blockJobInfo(disk_path, 0)
        if status == -1 and abort_on_error:
            msg = _('libvirt error while requesting blockjob info.')
            raise exception.NovaException(msg)
        try:
            cur = status.get('cur', 0)
            end = status.get('end', 0)
        except Exception:
            return False

        if wait_for_job_clean:
            job_ended = not status
        else:
            job_ended = cur == end

        return not job_ended

    def _can_quiesce(self, image_meta):
        if CONF.libvirt.virt_type not in ('kvm', 'qemu'):
            return (False, _('Only KVM and QEMU are supported'))

        if not self._host.has_min_version(MIN_LIBVIRT_FSFREEZE_VERSION):
            ver = ".".join([str(x) for x in MIN_LIBVIRT_FSFREEZE_VERSION])
            return (False, _('Quiescing requires libvirt version %(version)s '
                             'or greater') % {'version': ver})

        img_meta_prop = image_meta.get('properties', {}) if image_meta else {}
        hw_qga = img_meta_prop.get('hw_qemu_guest_agent', 'no')
        if hw_qga.lower() == 'no':
            return (False, _('QEMU guest agent is not enabled'))

        return (True, None)

    def _set_quiesced(self, context, instance, image_meta, quiesced):
        supported, reason = self._can_quiesce(image_meta)
        if not supported:
            raise exception.InstanceQuiesceNotSupported(
                instance_id=instance['uuid'], reason=reason)

        try:
            domain = self._get_domain(instance)
            if quiesced:
                domain.fsFreeze()
            else:
                domain.fsThaw()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            msg = (_('Error from libvirt while quiescing %(instance_name)s: '
                     '[Error Code %(error_code)s] %(ex)s')
                   % {'instance_name': instance['name'],
                      'error_code': error_code, 'ex': ex})
            raise exception.NovaException(msg)

    def quiesce(self, context, instance, image_meta):
        """Freeze the guest filesystems to prepare for snapshot.

        The qemu-guest-agent must be setup to execute fsfreeze.
        """
        self._set_quiesced(context, instance, image_meta, True)

    def unquiesce(self, context, instance, image_meta):
        """Thaw the guest filesystems after snapshot."""
        self._set_quiesced(context, instance, image_meta, False)

    def _live_snapshot(self, context, instance, domain, disk_path, out_path,
                       image_format, image_meta):
        """Snapshot an instance without downtime."""
        # Save a copy of the domain's persistent XML file
        xml = domain.XMLDesc(
            libvirt.VIR_DOMAIN_XML_INACTIVE |
            libvirt.VIR_DOMAIN_XML_SECURE)

        # Abort is an idempotent operation, so make sure any block
        # jobs which may have failed are ended.
        try:
            domain.blockJobAbort(disk_path, 0)
        except Exception:
            pass

        # NOTE (rmk): We are using shallow rebases as a workaround to a bug
        #             in QEMU 1.3. In order to do this, we need to create
        #             a destination image with the original backing file
        #             and matching size of the instance root disk.
        src_disk_size = libvirt_utils.get_disk_size(disk_path)
        src_back_path = libvirt_utils.get_disk_backing_file(disk_path,
                                                            basename=False)
        disk_delta = out_path + '.delta'
        libvirt_utils.create_cow_image(src_back_path, disk_delta,
                                       src_disk_size)

        img_meta_prop = image_meta.get('properties', {}) if image_meta else {}
        require_quiesce = img_meta_prop.get('os_require_quiesce', 'no')
        if require_quiesce.lower() == 'yes':
            self.quiesce(context, instance, image_meta)

        try:
            # NOTE (rmk): blockRebase cannot be executed on persistent
            #             domains, so we need to temporarily undefine it.
            #             If any part of this block fails, the domain is
            #             re-defined regardless.
            if domain.isPersistent():
                domain.undefine()

            # NOTE (rmk): Establish a temporary mirror of our root disk and
            #             issue an abort once we have a complete copy.
            domain.blockRebase(disk_path, disk_delta, 0,
                               libvirt.VIR_DOMAIN_BLOCK_REBASE_COPY |
                               libvirt.VIR_DOMAIN_BLOCK_REBASE_REUSE_EXT |
                               libvirt.VIR_DOMAIN_BLOCK_REBASE_SHALLOW)

            while self._wait_for_block_job(domain, disk_path):
                time.sleep(0.5)

            domain.blockJobAbort(disk_path, 0)
            libvirt_utils.chown(disk_delta, os.getuid())
        finally:
            self._conn.defineXML(xml)
            if require_quiesce.lower() == 'yes':
                self.unquiesce(context, instance, image_meta)

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
            LOG.exception(_LE('Failed to send updated snapshot status '
                              'to volume service.'))

    def _volume_snapshot_create(self, context, instance, domain,
                                volume_id, new_file):
        """Perform volume snapshot.

           :param domain: VM that volume is attached to
           :param volume_id: volume UUID to snapshot
           :param new_file: relative path to new qcow2 file present on share

        """

        xml = domain.XMLDesc(0)
        xml_doc = etree.fromstring(xml)

        device_info = vconfig.LibvirtConfigGuest()
        device_info.parse_dom(xml_doc)

        disks_to_snap = []          # to be snapshotted by libvirt
        network_disks_to_snap = []  # network disks (netfs, gluster, etc.)
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
            elif disk_info['source_protocol'] in ('gluster', 'netfs'):
                network_disks_to_snap.append((disk_info, new_file))

        if not disks_to_snap and not network_disks_to_snap:
            msg = _('Found no disk to snapshot.')
            raise exception.NovaException(msg)

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
        LOG.debug("snap xml: %s", snapshot_xml)

        snap_flags = (libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY |
                      libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA |
                      libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT)

        QUIESCE = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE

        try:
            domain.snapshotCreateXML(snapshot_xml,
                                     snap_flags | QUIESCE)

            return
        except libvirt.libvirtError:
            LOG.exception(_LE('Unable to create quiesced VM snapshot, '
                              'attempting again with quiescing disabled.'))

        try:
            domain.snapshotCreateXML(snapshot_xml, snap_flags)
        except libvirt.libvirtError:
            LOG.exception(_LE('Unable to create VM snapshot, '
                              'failing volume_snapshot operation.'))

            raise

    def _volume_refresh_connection_info(self, context, instance, volume_id):
        bdm = objects.BlockDeviceMapping.get_by_volume_id(context,
                                                          volume_id)
        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm)
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
            virt_dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)

        if create_info['type'] != 'qcow2':
            raise exception.NovaException(_('Unknown type: %s') %
                                          create_info['type'])

        snapshot_id = create_info.get('snapshot_id', None)
        if snapshot_id is None:
            raise exception.NovaException(_('snapshot_id required '
                                            'in create_info'))

        try:
            self._volume_snapshot_create(context, instance, virt_dom,
                                         volume_id, create_info['new_file'])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error occurred during '
                                  'volume_snapshot_create, '
                                  'sending error status to Cinder.'))
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


        Libvirt blockjob handling required for this method is broken
        in versions of libvirt that do not contain:
        http://libvirt.org/git/?p=libvirt.git;h=0f9e67bfad (1.1.1)
        (Patch is pending in 1.0.5-maint branch as well, but we cannot detect
        libvirt 1.0.5.5 vs. 1.0.5.6 here.)
        """

        if not self._host.has_min_version(MIN_LIBVIRT_BLOCKJOBINFO_VERSION):
            ver = '.'.join([str(x) for x in MIN_LIBVIRT_BLOCKJOBINFO_VERSION])
            msg = _("Libvirt '%s' or later is required for online deletion "
                    "of volume snapshots.") % ver
            raise exception.Invalid(msg)

        LOG.debug('volume_snapshot_delete: delete_info: %s', delete_info)

        if delete_info['type'] != 'qcow2':
            msg = _('Unknown delete_info type %s') % delete_info['type']
            raise exception.NovaException(msg)

        try:
            virt_dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)

        # Find dev name
        my_dev = None
        active_disk = None

        xml = virt_dom.XMLDesc(0)
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
            msg = _('Disk with id: %s '
                    'not found attached to instance.') % volume_id
            LOG.debug('Domain XML: %s', xml)
            raise exception.NovaException(msg)

        LOG.debug("found device at %s", my_dev)

        def _get_snap_dev(filename, backing_store):
            if filename is None:
                msg = _('filename cannot be None')
                raise exception.NovaException(msg)

            # libgfapi delete
            LOG.debug("XML: %s" % xml)

            LOG.debug("active disk object: %s" % active_disk_object)

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
                    LOG.debug('found match: %s' % b.source_name)
                    matched_name = b.source_name
                    index = b.index
                    break

                b = b.backing_store

            if matched_name is None:
                msg = _('no match found for %s') % (filename_to_merge)
                raise exception.NovaException(msg)

            LOG.debug('index of match (%s) is %s' % (b.source_name, index))

            my_snap_dev = '%s[%s]' % (my_dev, index)
            return my_snap_dev

        if delete_info['merge_target_file'] is None:
            # pull via blockRebase()

            # Merge the most recent snapshot into the active image

            rebase_disk = my_dev
            rebase_flags = 0
            rebase_base = delete_info['file_to_merge']  # often None
            if active_protocol is not None:
                rebase_base = _get_snap_dev(delete_info['file_to_merge'],
                                            active_disk_object.backing_store)
            rebase_bw = 0

            LOG.debug('disk: %(disk)s, base: %(base)s, '
                      'bw: %(bw)s, flags: %(flags)s',
                      {'disk': rebase_disk,
                       'base': rebase_base,
                       'bw': rebase_bw,
                       'flags': rebase_flags})

            result = virt_dom.blockRebase(rebase_disk, rebase_base,
                                          rebase_bw, rebase_flags)

            if result == 0:
                LOG.debug('blockRebase started successfully')

            while self._wait_for_block_job(virt_dom, my_dev,
                                           abort_on_error=True):
                LOG.debug('waiting for blockRebase job completion')
                time.sleep(0.5)

        else:
            # commit with blockCommit()
            my_snap_base = None
            my_snap_top = None
            commit_disk = my_dev
            commit_flags = 0

            if active_protocol is not None:
                my_snap_base = _get_snap_dev(delete_info['merge_target_file'],
                                             active_disk_object.backing_store)
                my_snap_top = _get_snap_dev(delete_info['file_to_merge'],
                                            active_disk_object.backing_store)
                try:
                    commit_flags |= libvirt.VIR_DOMAIN_BLOCK_COMMIT_RELATIVE
                except AttributeError:
                    ver = '.'.join(
                        [str(x) for x in
                         MIN_LIBVIRT_BLOCKCOMMIT_RELATIVE_VERSION])
                    msg = _("Relative blockcommit support was not detected. "
                            "Libvirt '%s' or later is required for online "
                            "deletion of network storage-backed volume "
                            "snapshots.") % ver
                    raise exception.Invalid(msg)

            commit_base = my_snap_base or delete_info['merge_target_file']
            commit_top = my_snap_top or delete_info['file_to_merge']
            bandwidth = 0

            LOG.debug('will call blockCommit with commit_disk=%(commit_disk)s '
                      'commit_base=%(commit_base)s '
                      'commit_top=%(commit_top)s '
                      % {'commit_disk': commit_disk,
                         'commit_base': commit_base,
                         'commit_top': commit_top})

            result = virt_dom.blockCommit(commit_disk, commit_base, commit_top,
                                          bandwidth, commit_flags)

            if result == 0:
                LOG.debug('blockCommit started successfully')

            while self._wait_for_block_job(virt_dom, my_dev,
                                           abort_on_error=True):
                LOG.debug('waiting for blockCommit job completion')
                time.sleep(0.5)

    def volume_snapshot_delete(self, context, instance, volume_id, snapshot_id,
                               delete_info):
        try:
            self._volume_snapshot_delete(context, instance, volume_id,
                                         snapshot_id, delete_info=delete_info)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE('Error occurred during '
                                  'volume_snapshot_delete, '
                                  'sending error status to Cinder.'))
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
                LOG.debug("Instance soft reboot failed: %s", e)
                soft_reboot_success = False

            if soft_reboot_success:
                LOG.info(_LI("Instance soft rebooted successfully."),
                         instance=instance)
                return
            else:
                LOG.warn(_LW("Failed to soft reboot instance. "
                             "Trying hard reboot."),
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
        dom = self._get_domain(instance)
        state = LIBVIRT_POWER_STATE[dom.info()[0]]
        old_domid = dom.ID()
        # NOTE(vish): This check allows us to reboot an instance that
        #             is already shutdown.
        if state == power_state.RUNNING:
            dom.shutdown()
        # NOTE(vish): This actually could take slightly longer than the
        #             FLAG defines depending on how long the get_info
        #             call takes to return.
        self._prepare_pci_devices_for_use(
            pci_manager.get_instance_pci_devs(instance, 'all'))
        for x in xrange(CONF.libvirt.wait_soft_reboot_seconds):
            dom = self._get_domain(instance)
            state = LIBVIRT_POWER_STATE[dom.info()[0]]
            new_domid = dom.ID()

            # NOTE(ivoks): By checking domain IDs, we make sure we are
            #              not recreating domain that's already running.
            if old_domid != new_domid:
                if state in [power_state.SHUTDOWN,
                             power_state.CRASHED]:
                    LOG.info(_LI("Instance shutdown successfully."),
                             instance=instance)
                    self._create_domain(domain=dom)
                    timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_running, instance)
                    timer.start(interval=0.5).wait()
                    return True
                else:
                    LOG.info(_LI("Instance may have been rebooted during soft "
                                 "reboot, so return now."), instance=instance)
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

        If xml is set, it uses the passed in xml in place of the xml from the
        existing domain.
        """

        self._destroy(instance)

        # Get the system metadata from the instance
        system_meta = utils.instance_sys_meta(instance)

        # Convert the system metadata to image metadata
        image_meta = utils.get_image_from_system_metadata(system_meta)
        # NOTE(stpierre): In certain cases -- e.g., when booting a
        #                 guest to restore its state after restarting
        #                 Nova compute -- the context is not
        #                 populated, which causes this (and
        #                 _create_images_and_backing below) to error.
        if not image_meta and context.auth_token is not None:
            image_ref = instance.get('image_ref')
            image_meta = compute_utils.get_image_metadata(context,
                                                          self._image_api,
                                                          image_ref,
                                                          instance)

        instance_dir = libvirt_utils.get_instance_path(instance)
        fileutils.ensure_tree(instance_dir)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        # NOTE(vish): This could generate the wrong device_format if we are
        #             using the raw backend and the images don't exist yet.
        #             The create_images_and_backing below doesn't properly
        #             regenerate raw backend images, however, so when it
        #             does we need to (re)generate the xml after the images
        #             are in place.
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  image_meta=image_meta,
                                  block_device_info=block_device_info,
                                  write_to_disk=True)

        # NOTE (rmk): Re-populate any missing backing files.
        disk_info_json = self._get_instance_disk_info(instance['name'], xml,
                                                      block_device_info)

        if context.auth_token is not None:
            self._create_images_and_backing(context, instance, instance_dir,
                                            disk_info_json)

        # Initialize all the necessary networking, block devices and
        # start the instance.
        self._create_domain_and_network(context, xml, instance, network_info,
                                        disk_info,
                                        block_device_info=block_device_info,
                                        reboot=True,
                                        vifs_already_plugged=True)
        self._prepare_pci_devices_for_use(
            pci_manager.get_instance_pci_devs(instance, 'all'))

        def _wait_for_reboot():
            """Called at an interval until the VM is running again."""
            state = self.get_info(instance).state

            if state == power_state.RUNNING:
                LOG.info(_LI("Instance rebooted successfully."),
                         instance=instance)
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot)
        timer.start(interval=0.5).wait()

    def pause(self, instance):
        """Pause VM instance."""
        dom = self._get_domain(instance)
        dom.suspend()

    def unpause(self, instance):
        """Unpause paused VM instance."""
        dom = self._get_domain(instance)
        dom.resume()

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
            dom = self._get_domain(instance)
        except exception.InstanceNotFound:
            # If the instance has gone then we don't need to
            # wait for it to shutdown
            return True

        (state, _max_mem, _mem, _cpus, _t) = dom.info()
        state = LIBVIRT_POWER_STATE[state]
        if state in SHUTDOWN_STATES:
            LOG.info(_LI("Instance already shutdown."),
                     instance=instance)
            return True

        LOG.debug("Shutting down instance from state %s", state,
                  instance=instance)
        dom.shutdown()
        retry_countdown = retry_interval

        for sec in six.moves.range(timeout):

            dom = self._get_domain(instance)
            (state, _max_mem, _mem, _cpus, _t) = dom.info()
            state = LIBVIRT_POWER_STATE[state]

            if state in SHUTDOWN_STATES:
                LOG.info(_LI("Instance shutdown successfully after %d "
                              "seconds."), sec, instance=instance)
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
                    dom.shutdown()
                except libvirt.libvirtError:
                    # Assume this is because its now shutdown, so loop
                    # one more time to clean up.
                    LOG.debug("Ignoring libvirt exception from shutdown "
                              "request.", instance=instance)
                    continue
            else:
                retry_countdown -= 1

            time.sleep(1)

        LOG.info(_LI("Instance failed to shutdown in %d seconds."),
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

    def suspend(self, instance):
        """Suspend the specified instance."""
        dom = self._get_domain(instance)
        self._detach_pci_devices(dom,
            pci_manager.get_instance_pci_devs(instance))
        self._detach_sriov_ports(instance, dom)
        dom.managedSave(0)

    def resume(self, context, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        image_meta = compute_utils.get_image_metadata(context,
                self._image_api, instance.image_ref, instance)

        disk_info = blockinfo.get_disk_info(
                CONF.libvirt.virt_type, instance,
                block_device_info=block_device_info, image_meta=image_meta)

        xml = self._get_existing_domain_xml(instance, network_info,
                                            block_device_info)
        dom = self._create_domain_and_network(context, xml, instance,
                           network_info, disk_info,
                           block_device_info=block_device_info,
                           vifs_already_plugged=True)
        self._attach_pci_devices(dom,
            pci_manager.get_instance_pci_devs(instance))
        self._attach_sriov_ports(context, instance, dom, network_info)

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        # Check if the instance is running already and avoid doing
        # anything if it is.
        try:
            domain = self._get_domain(instance)
            state = LIBVIRT_POWER_STATE[domain.info()[0]]

            ignored_states = (power_state.RUNNING,
                              power_state.SUSPENDED,
                              power_state.NOSTATE,
                              power_state.PAUSED)

            if state in ignored_states:
                return
        except exception.NovaException:
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

        if image_meta is not None:
            rescue_image_id = image_meta.get('id')
        else:
            rescue_image_id = None

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
                                            None,
                                            image_meta,
                                            rescue=True)
        self._create_image(context, instance, disk_info['mapping'],
                           suffix='.rescue', disk_images=rescue_images,
                           network_info=network_info,
                           admin_pass=rescue_password)
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  image_meta, rescue=rescue_images,
                                  write_to_disk=True)
        self._destroy(instance)
        self._create_domain(xml)

    def unrescue(self, instance, network_info):
        """Reboot the VM which is being rescued back into primary images.
        """
        instance_dir = libvirt_utils.get_instance_path(instance)
        unrescue_xml_path = os.path.join(instance_dir, 'unrescue.xml')
        xml = libvirt_utils.load_file(unrescue_xml_path)
        virt_dom = self._get_domain(instance)
        self._destroy(instance)
        self._create_domain(xml, virt_dom)
        libvirt_utils.file_delete(unrescue_xml_path)
        rescue_files = os.path.join(instance_dir, "*.rescue")
        for rescue_file in glob.iglob(rescue_files):
            libvirt_utils.file_delete(rescue_file)

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def _enable_hairpin(self, xml):
        interfaces = self._get_interfaces(xml)
        for interface in interfaces:
            utils.execute('tee',
                          '/sys/class/net/%s/brport/hairpin_mode' % interface,
                          process_input='1',
                          run_as_root=True,
                          check_exit_code=[0, 1])

    # NOTE(ilyaalekseyev): Implementation like in multinics
    # for xenapi(tr3buchet)
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None,
              flavor=None):
        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        self._create_image(context, instance,
                           disk_info['mapping'],
                           network_info=network_info,
                           block_device_info=block_device_info,
                           files=injected_files,
                           admin_pass=admin_password)
        xml = self._get_guest_xml(context, instance, network_info,
                                  disk_info, image_meta,
                                  block_device_info=block_device_info,
                                  write_to_disk=True,
                                  flavor=flavor)
        self._create_domain_and_network(context, xml, instance, network_info,
                                        disk_info,
                                        block_device_info=block_device_info)
        LOG.debug("Instance is running", instance=instance)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            state = self.get_info(instance).state

            if state == power_state.RUNNING:
                LOG.info(_LI("Instance spawned successfully."),
                         instance=instance)
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
        LOG.info(_LI('data: %(data)r, fpath: %(fpath)r'),
                 {'data': data, 'fpath': fpath})
        with open(fpath, 'a+') as fp:
            fp.write(data)

        return fpath

    def get_console_output(self, context, instance):
        virt_dom = self._get_domain(instance)
        xml = virt_dom.XMLDesc(0)
        tree = etree.fromstring(xml)

        console_types = {}

        # NOTE(comstud): We want to try 'file' types first, then try 'pty'
        # types.  We can't use Python 2.7 syntax of:
        # tree.find("./devices/console[@type='file']/source")
        # because we need to support 2.6.
        console_nodes = tree.findall('./devices/console')
        for console_node in console_nodes:
            console_type = console_node.get('type')
            console_types.setdefault(console_type, [])
            console_types[console_type].append(console_node)

        # If the guest has a console logging to a file prefer to use that
        if console_types.get('file'):
            for file_console in console_types.get('file'):
                source_node = file_console.find('./source')
                if source_node is None:
                    continue
                path = source_node.get("path")
                if not path:
                    continue

                if not os.path.exists(path):
                    LOG.info(_LI('Instance is configured with a file console, '
                                 'but the backing file is not (yet?) present'),
                             instance=instance)
                    return ""

                libvirt_utils.chown(path, os.getuid())

                with libvirt_utils.file_open(path, 'rb') as fp:
                    log_data, remaining = utils.last_bytes(fp,
                                                           MAX_CONSOLE_BYTES)
                    if remaining > 0:
                        LOG.info(_LI('Truncated console log returned, '
                                     '%d bytes ignored'), remaining,
                                 instance=instance)
                    return log_data

        # Try 'pty' types
        if console_types.get('pty'):
            for pty_console in console_types.get('pty'):
                source_node = pty_console.find('./source')
                if source_node is None:
                    continue
                pty = source_node.get("path")
                if not pty:
                    continue
                break
        else:
            msg = _("Guest does not have a console available")
            raise exception.NovaException(msg)

        self._chown_console_log_for_instance(instance)
        data = self._flush_libvirt_console(pty)
        console_log = self._get_console_log_path(instance)
        fpath = self._append_to_file(data, console_log)

        with libvirt_utils.file_open(fpath, 'rb') as fp:
            log_data, remaining = utils.last_bytes(fp, MAX_CONSOLE_BYTES)
            if remaining > 0:
                LOG.info(_LI('Truncated console log returned, '
                             '%d bytes ignored'),
                         remaining, instance=instance)
            return log_data

    @staticmethod
    def get_host_ip_addr():
        return CONF.my_ip

    def get_vnc_console(self, context, instance):
        def get_vnc_port_for_instance(instance_name):
            virt_dom = self._get_domain(instance)
            xml = virt_dom.XMLDesc(0)
            dom = minidom.parseString(xml)

            for graphic in dom.getElementsByTagName('graphics'):
                if graphic.getAttribute('type') == 'vnc':
                    return graphic.getAttribute('port')
            # NOTE(rmk): We had VNC consoles enabled but the instance in
            # question is not actually listening for connections.
            raise exception.ConsoleTypeUnavailable(console_type='vnc')

        port = get_vnc_port_for_instance(instance.name)
        host = CONF.vncserver_proxyclient_address

        return ctype.ConsoleVNC(host=host, port=port)

    def get_spice_console(self, context, instance):
        def get_spice_ports_for_instance(instance_name):
            virt_dom = self._get_domain(instance)
            xml = virt_dom.XMLDesc(0)
            # TODO(sleepsonthefloor): use etree instead of minidom
            dom = minidom.parseString(xml)

            for graphic in dom.getElementsByTagName('graphics'):
                if graphic.getAttribute('type') == 'spice':
                    return (graphic.getAttribute('port'),
                            graphic.getAttribute('tlsPort'))
            # NOTE(rmk): We had Spice consoles enabled but the instance in
            # question is not actually listening for connections.
            raise exception.ConsoleTypeUnavailable(console_type='spice')

        ports = get_spice_ports_for_instance(instance['name'])
        host = CONF.spice.server_proxyclient_address

        return ctype.ConsoleSpice(host=host, port=ports[0], tlsPort=ports[1])

    def get_serial_console(self, context, instance):
        for hostname, port in self._get_serial_ports_from_instance(
                instance, mode='bind'):
            return ctype.ConsoleSerial(host=hostname, port=port)
        raise exception.ConsoleTypeUnavailable(console_type='serial')

    @staticmethod
    def _supports_direct_io(dirpath):

        if not hasattr(os, 'O_DIRECT'):
            LOG.debug("This python runtime does not support direct I/O")
            return False

        testfile = os.path.join(dirpath, ".directio.test")

        hasDirectIO = True
        try:
            f = os.open(testfile, os.O_CREAT | os.O_WRONLY | os.O_DIRECT)
            # Check is the write allowed with 512 byte alignment
            align_size = 512
            m = mmap.mmap(-1, align_size)
            m.write(r"x" * align_size)
            os.write(f, m)
            os.close(f)
            LOG.debug("Path '%(path)s' supports direct I/O",
                      {'path': dirpath})
        except OSError as e:
            if e.errno == errno.EINVAL:
                LOG.debug("Path '%(path)s' does not support direct I/O: "
                          "'%(ex)s'", {'path': dirpath, 'ex': e})
                hasDirectIO = False
            else:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE("Error on '%(path)s' while checking "
                                  "direct I/O: '%(ex)s'"),
                              {'path': dirpath, 'ex': e})
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Error on '%(path)s' while checking direct I/O: "
                              "'%(ex)s'"), {'path': dirpath, 'ex': e})
        finally:
            try:
                os.unlink(testfile)
            except Exception:
                pass

        return hasDirectIO

    @staticmethod
    def _create_local(target, local_size, unit='G',
                      fs_format=None, label=None):
        """Create a blank image of specified size."""

        libvirt_utils.create_image('raw', target,
                                    '%d%c' % (local_size, unit))

    def _create_ephemeral(self, target, ephemeral_size,
                          fs_label, os_type, is_block_dev=False,
                          max_size=None, context=None, specified_fs=None):
        if not is_block_dev:
            self._create_local(target, ephemeral_size)

        # Run as root only for block devices.
        disk.mkfs(os_type, fs_label, target, run_as_root=is_block_dev,
                  specified_fs=specified_fs)

    @staticmethod
    def _create_swap(target, swap_mb, max_size=None, context=None):
        """Create a swap file of specified size."""
        libvirt_utils.create_image('raw', target, '%dM' % swap_mb)
        utils.mkfs('swap', target)

    @staticmethod
    def _get_console_log_path(instance):
        return os.path.join(libvirt_utils.get_instance_path(instance),
                            'console.log')

    @staticmethod
    def _get_disk_config_path(instance, suffix=''):
        return os.path.join(libvirt_utils.get_instance_path(instance),
                            'disk.config' + suffix)

    def _chown_console_log_for_instance(self, instance):
        console_log = self._get_console_log_path(instance)
        if os.path.exists(console_log):
            libvirt_utils.chown(console_log, os.getuid())

    def _chown_disk_config_for_instance(self, instance):
        disk_config = self._get_disk_config_path(instance)
        if os.path.exists(disk_config):
            libvirt_utils.chown(disk_config, os.getuid())

    @staticmethod
    def _is_booted_from_volume(instance, disk_mapping):
        """Determines whether the VM is booting from volume

        Determines whether the disk mapping indicates that the VM
        is booting from a volume.
        """
        return ((not bool(instance.get('image_ref')))
                or 'disk' not in disk_mapping)

    def _inject_data(self, instance, network_info, admin_pass, files, suffix):
        """Injects data in a disk image

        Helper used for injecting data in a disk image file system.

        Keyword arguments:
          instance -- a dict that refers instance specifications
          network_info -- a dict that refers network speficications
          admin_pass -- a string used to set an admin password
          files -- a list of files needs to be injected
          suffix -- a string used as an image name suffix
        """
        # Handles the partition need to be used.
        target_partition = None
        if not instance['kernel_id']:
            target_partition = CONF.libvirt.inject_partition
            if target_partition == 0:
                target_partition = None
        if CONF.libvirt.virt_type == 'lxc':
            target_partition = None

        # Handles the key injection.
        if CONF.libvirt.inject_key and instance.get('key_data'):
            key = str(instance['key_data'])
        else:
            key = None

        # Handles the admin password injection.
        if not CONF.libvirt.inject_password:
            admin_pass = None

        # Handles the network injection.
        net = netutils.get_injected_network_template(
                network_info, libvirt_virt_type=CONF.libvirt.virt_type)

        # Handles the metadata injection
        metadata = instance.get('metadata')

        image_type = CONF.libvirt.images_type
        if any((key, net, metadata, admin_pass, files)):
            injection_image = self.image_backend.image(
                instance,
                'disk' + suffix,
                image_type)
            img_id = instance['image_ref']

            if not injection_image.check_image_exists():
                LOG.warn(_LW('Image %s not found on disk storage. '
                         'Continue without injecting data'),
                         injection_image.path, instance=instance)
                return
            try:
                disk.inject_data(injection_image.path,
                                 key, net, metadata, admin_pass, files,
                                 partition=target_partition,
                                 use_cow=CONF.use_cow_images,
                                 mandatory=('files',))
            except Exception as e:
                with excutils.save_and_reraise_exception():
                    LOG.error(_LE('Error injecting data into image '
                                  '%(img_id)s (%(e)s)'),
                              {'img_id': img_id, 'e': e},
                              instance=instance)

    def _create_image(self, context, instance,
                      disk_mapping, suffix='',
                      disk_images=None, network_info=None,
                      block_device_info=None, files=None,
                      admin_pass=None, inject_files=True):
        booted_from_volume = self._is_booted_from_volume(
            instance, disk_mapping)

        def image(fname, image_type=CONF.libvirt.images_type):
            return self.image_backend.image(instance,
                                            fname + suffix, image_type)

        def raw(fname):
            return image(fname, image_type='raw')

        # ensure directories exist and are writable
        fileutils.ensure_tree(libvirt_utils.get_instance_path(instance))

        LOG.info(_LI('Creating image'), instance=instance)

        # NOTE(dprince): for rescue console.log may already exist... chown it.
        self._chown_console_log_for_instance(instance)

        # NOTE(yaguang): For evacuate disk.config already exist in shared
        # storage, chown it.
        self._chown_disk_config_for_instance(instance)

        # NOTE(vish): No need add the suffix to console.log
        libvirt_utils.write_to_file(
            self._get_console_log_path(instance), '', 7)

        if not disk_images:
            disk_images = {'image_id': instance['image_ref'],
                           'kernel_id': instance['kernel_id'],
                           'ramdisk_id': instance['ramdisk_id']}

        if disk_images['kernel_id']:
            fname = imagecache.get_cache_fname(disk_images, 'kernel_id')
            raw('kernel').cache(fetch_func=libvirt_utils.fetch_image,
                                context=context,
                                filename=fname,
                                image_id=disk_images['kernel_id'],
                                user_id=instance['user_id'],
                                project_id=instance['project_id'])
            if disk_images['ramdisk_id']:
                fname = imagecache.get_cache_fname(disk_images, 'ramdisk_id')
                raw('ramdisk').cache(fetch_func=libvirt_utils.fetch_image,
                                     context=context,
                                     filename=fname,
                                     image_id=disk_images['ramdisk_id'],
                                     user_id=instance['user_id'],
                                     project_id=instance['project_id'])

        inst_type = instance.get_flavor()

        # NOTE(ndipanov): Even if disk_mapping was passed in, which
        # currently happens only on rescue - we still don't want to
        # create a base image.
        if not booted_from_volume:
            root_fname = imagecache.get_cache_fname(disk_images, 'image_id')
            size = instance['root_gb'] * units.Gi

            if size == 0 or suffix == '.rescue':
                size = None

            backend = image('disk')
            if backend.SUPPORTS_CLONE:
                def clone_fallback_to_fetch(*args, **kwargs):
                    try:
                        backend.clone(context, disk_images['image_id'])
                    except exception.ImageUnacceptable:
                        libvirt_utils.fetch_image(*args, **kwargs)
                fetch_func = clone_fallback_to_fetch
            else:
                fetch_func = libvirt_utils.fetch_image
            backend.cache(fetch_func=fetch_func,
                          context=context,
                          filename=root_fname,
                          size=size,
                          image_id=disk_images['image_id'],
                          user_id=instance['user_id'],
                          project_id=instance['project_id'])

        # Lookup the filesystem type if required
        os_type_with_default = disk.get_fs_type_for_os_type(
                                                          instance['os_type'])

        ephemeral_gb = instance['ephemeral_gb']
        if 'disk.local' in disk_mapping:
            disk_image = image('disk.local')
            fn = functools.partial(self._create_ephemeral,
                                   fs_label='ephemeral0',
                                   os_type=instance["os_type"],
                                   is_block_dev=disk_image.is_block_dev)
            fname = "ephemeral_%s_%s" % (ephemeral_gb, os_type_with_default)
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
                                   os_type=instance["os_type"],
                                   is_block_dev=disk_image.is_block_dev)
            size = eph['size'] * units.Gi
            fname = "ephemeral_%s_%s" % (eph['size'], os_type_with_default)
            disk_image.cache(fetch_func=fn,
                             context=context,
                             filename=fname,
                             size=size,
                             ephemeral_size=eph['size'],
                             specified_fs=specified_fs)

        if 'disk.swap' in disk_mapping:
            mapping = disk_mapping['disk.swap']
            swap_mb = 0

            swap = driver.block_device_info_get_swap(block_device_info)
            if driver.swap_is_usable(swap):
                swap_mb = swap['swap_size']
            elif (inst_type['swap'] > 0 and
                  not block_device.volume_in_mapping(
                    mapping['dev'], block_device_info)):
                swap_mb = inst_type['swap']

            if swap_mb > 0:
                size = swap_mb * units.Mi
                image('disk.swap').cache(fetch_func=self._create_swap,
                                         context=context,
                                         filename="swap_%s" % swap_mb,
                                         size=size,
                                         swap_mb=swap_mb)

        # Config drive
        if configdrive.required_by(instance):
            LOG.info(_LI('Using config drive'), instance=instance)
            extra_md = {}
            if admin_pass:
                extra_md['admin_pass'] = admin_pass

            inst_md = instance_metadata.InstanceMetadata(instance,
                content=files, extra_md=extra_md, network_info=network_info)
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                configdrive_path = self._get_disk_config_path(instance, suffix)
                LOG.info(_LI('Creating config drive at %(path)s'),
                         {'path': configdrive_path}, instance=instance)

                try:
                    cdb.make_drive(configdrive_path)
                except processutils.ProcessExecutionError as e:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_LE('Creating config drive failed '
                                      'with error: %s'),
                                  e, instance=instance)

        # File injection only if needed
        elif inject_files and CONF.libvirt.inject_partition != -2:
            if booted_from_volume:
                LOG.warn(_LW('File injection into a boot from volume '
                             'instance is not supported'), instance=instance)
            self._inject_data(
                instance, network_info, admin_pass, files, suffix)

        if CONF.libvirt.virt_type == 'uml':
            libvirt_utils.chown(image('disk').path, 'root')

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
                        self._conn.nodeDeviceLookupByName(libvirt_dev_addr)
                # Note(yjiang5) Spelling for 'dettach' is correct, see
                # http://libvirt.org/html/libvirt-libvirt.html.
                libvirt_dev.dettach()

            # Note(yjiang5): A reset of one PCI device may impact other
            # devices on the same bus, thus we need two separated loops
            # to detach and then reset it.
            for dev in pci_devices:
                libvirt_dev_addr = dev['hypervisor_name']
                libvirt_dev = \
                        self._conn.nodeDeviceLookupByName(libvirt_dev_addr)
                libvirt_dev.reset()

        except libvirt.libvirtError as exc:
            raise exception.PciDevicePrepareFailed(id=dev['id'],
                                                   instance_uuid=
                                                   dev['instance_uuid'],
                                                   reason=six.text_type(exc))

    def _detach_pci_devices(self, dom, pci_devs):

        # for libvirt version < 1.1.1, this is race condition
        # so forbid detach if not had this version
        if not self._host.has_min_version(MIN_LIBVIRT_DEVICE_CALLBACK_VERSION):
            if pci_devs:
                reason = (_("Detaching PCI devices with libvirt < %(ver)s"
                           " is not permitted") %
                           {'ver': MIN_LIBVIRT_DEVICE_CALLBACK_VERSION})
                raise exception.PciDeviceDetachFailed(reason=reason,
                                                      dev=pci_devs)
        try:
            for dev in pci_devs:
                dom.detachDeviceFlags(self._get_guest_pci_device(dev).to_xml(),
                                      libvirt.VIR_DOMAIN_AFFECT_LIVE)
                # after detachDeviceFlags returned, we should check the dom to
                # ensure the detaching is finished
                xml = dom.XMLDesc(0)
                xml_doc = etree.fromstring(xml)
                guest_config = vconfig.LibvirtConfigGuest()
                guest_config.parse_dom(xml_doc)

                for hdev in [d for d in guest_config.devices
                    if isinstance(d, vconfig.LibvirtConfigGuestHostdevPCI)]:
                    hdbsf = [hdev.domain, hdev.bus, hdev.slot, hdev.function]
                    dbsf = pci_utils.parse_address(dev['address'])
                    if [int(x, 16) for x in hdbsf] ==\
                            [int(x, 16) for x in dbsf]:
                        raise exception.PciDeviceDetachFailed(reason=
                                                              "timeout",
                                                              dev=dev)

        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                LOG.warn(_LW("Instance disappeared while detaching "
                             "a PCI device from it."))
            else:
                raise

    def _attach_pci_devices(self, dom, pci_devs):
        try:
            for dev in pci_devs:
                dom.attachDevice(self._get_guest_pci_device(dev).to_xml())

        except libvirt.libvirtError:
            LOG.error(_LE('Attaching PCI devices %(dev)s to %(dom)s failed.'),
                      {'dev': pci_devs, 'dom': dom.ID()})
            raise

    def _prepare_args_for_get_config(self, context, instance):
        with utils.temporary_mutation(context, read_deleted="yes"):
            flavor = objects.Flavor.get_by_id(context,
                instance['instance_type_id'])
        image_ref = instance['image_ref']
        image_meta = compute_utils.get_image_metadata(
                            context, self._image_api, image_ref, instance)
        return flavor, image_meta

    @staticmethod
    def _has_sriov_port(network_info):
        for vif in network_info:
            if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
                return True
        return False

    def _attach_sriov_ports(self, context, instance, dom, network_info=None):
        if network_info is None:
            network_info = instance.info_cache.network_info
        if network_info is None:
            return

        if self._has_sriov_port(network_info):
            flavor, image_meta = self._prepare_args_for_get_config(context,
                                                                   instance)
            for vif in network_info:
                if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
                    cfg = self.vif_driver.get_config(instance,
                                                     vif,
                                                     image_meta,
                                                     flavor,
                                                     CONF.libvirt.virt_type)
                    LOG.debug('Attaching SR-IOV port %(port)s to %(dom)s',
                          {'port': vif, 'dom': dom.ID()})
                    dom.attachDevice(cfg.to_xml())

    def _detach_sriov_ports(self, instance, dom):
        network_info = instance.info_cache.network_info
        if network_info is None:
            return

        context = nova_context.get_admin_context()
        if self._has_sriov_port(network_info):
            # for libvirt version < 1.1.1, this is race condition
            # so forbid detach if it's an older version
            if not self._host.has_min_version(
                            MIN_LIBVIRT_DEVICE_CALLBACK_VERSION):
                reason = (_("Detaching SR-IOV ports with"
                           " libvirt < %(ver)s is not permitted") %
                           {'ver': MIN_LIBVIRT_DEVICE_CALLBACK_VERSION})
                raise exception.PciDeviceDetachFailed(reason=reason,
                                                      dev=network_info)

            flavor, image_meta = self._prepare_args_for_get_config(context,
                                                                   instance)
            for vif in network_info:
                if vif['vnic_type'] == network_model.VNIC_TYPE_DIRECT:
                    cfg = self.vif_driver.get_config(instance,
                                                     vif,
                                                     image_meta,
                                                     flavor,
                                                     CONF.libvirt.virt_type)
                    dom.detachDeviceFlags(cfg.to_xml(),
                                          libvirt.VIR_DOMAIN_AFFECT_LIVE)

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
                       if disable_service else DISABLE_REASON_UNDEFINED)
                    service.save()
                    LOG.debug('Updating compute service status to %s',
                              status_name[disable_service])
                else:
                    LOG.debug('Not overriding manual compute service '
                              'status with: %s',
                              status_name[disable_service])
        except exception.ComputeHostNotFound:
            LOG.warn(_LW('Cannot update service status on host: %s,'
                         'since it is not registered.'), CONF.host)
        except Exception:
            LOG.warn(_LW('Cannot update service status on host: %s,'
                         'due to an unexpected exception.'), CONF.host,
                     exc_info=True)

    def _get_host_capabilities(self):
        """Returns an instance of config.LibvirtConfigCaps representing
           the capabilities of the host.
        """
        if not self._caps:
            xmlstr = self._conn.getCapabilities()
            self._caps = vconfig.LibvirtConfigCaps()
            self._caps.parse_str(xmlstr)
            if hasattr(libvirt, 'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES'):
                try:
                    features = self._conn.baselineCPU(
                        [self._caps.host.cpu.to_xml()],
                        libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)
                    # FIXME(wangpan): the return value of baselineCPU should be
                    #                 None or xml string, but libvirt has a bug
                    #                 of it from 1.1.2 which is fixed in 1.2.0,
                    #                 this -1 checking should be removed later.
                    if features and features != -1:
                        cpu = vconfig.LibvirtConfigCPU()
                        cpu.parse_str(features)
                        self._caps.host.cpu.features = cpu.features
                except libvirt.libvirtError as ex:
                    error_code = ex.get_error_code()
                    if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                        LOG.warn(_LW("URI %(uri)s does not support full set"
                                     " of host capabilities: " "%(error)s"),
                                     {'uri': self.uri(), 'error': ex})
                    else:
                        raise
        return self._caps

    def _get_guest_cpu_model_config(self):
        mode = CONF.libvirt.cpu_mode
        model = CONF.libvirt.cpu_model

        if (CONF.libvirt.virt_type == "kvm" or
            CONF.libvirt.virt_type == "qemu"):
            if mode is None:
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

        LOG.debug("CPU mode '%(mode)s' model '%(model)s' was chosen",
                  {'mode': mode, 'model': (model or "")})

        cpu = vconfig.LibvirtConfigGuestCPU()
        cpu.mode = mode
        cpu.model = model

        return cpu

    def _get_guest_cpu_config(self, flavor, image, guest_cpu_numa):
        cpu = self._get_guest_cpu_model_config()

        if cpu is None:
            return None

        topology = hardware.get_best_cpu_topology(flavor, image)

        cpu.sockets = topology.sockets
        cpu.cores = topology.cores
        cpu.threads = topology.threads
        cpu.numa = guest_cpu_numa

        return cpu

    def _get_guest_disk_config(self, instance, name, disk_mapping, inst_type,
                               image_type=None):
        if CONF.libvirt.hw_disk_discard:
            if not self._host.has_min_version(MIN_LIBVIRT_DISCARD_VERSION,
                                              MIN_QEMU_DISCARD_VERSION,
                                              REQ_HYPERVISOR_DISCARD):
                msg = (_('Volume sets discard option, but libvirt %(libvirt)s'
                         ' or later is required, qemu %(qemu)s'
                         ' or later is required.') %
                      {'libvirt': MIN_LIBVIRT_DISCARD_VERSION,
                       'qemu': MIN_QEMU_DISCARD_VERSION})
                raise exception.Invalid(msg)

        image = self.image_backend.image(instance,
                                         name,
                                         image_type)
        disk_info = disk_mapping[name]
        return image.libvirt_info(disk_info['bus'],
                                  disk_info['dev'],
                                  disk_info['type'],
                                  self.disk_cachemode,
                                  inst_type['extra_specs'],
                                  self._get_hypervisor_version())

    def _get_guest_storage_config(self, instance, image_meta,
                                  disk_info,
                                  rescue, block_device_info,
                                  inst_type):
        devices = []
        disk_mapping = disk_info['mapping']

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        mount_rootfs = CONF.libvirt.virt_type == "lxc"
        if mount_rootfs:
            fs = vconfig.LibvirtConfigGuestFilesys()
            fs.source_type = "mount"
            fs.source_dir = os.path.join(
                libvirt_utils.get_instance_path(instance), 'rootfs')
            devices.append(fs)
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

                for idx, eph in enumerate(
                    driver.block_device_info_get_ephemerals(
                        block_device_info)):
                    diskeph = self._get_guest_disk_config(
                        instance,
                        blockinfo.get_eph_disk(idx),
                        disk_mapping, inst_type)
                    devices.append(diskeph)

                if 'disk.swap' in disk_mapping:
                    diskswap = self._get_guest_disk_config(instance,
                                                           'disk.swap',
                                                           disk_mapping,
                                                           inst_type)
                    devices.append(diskswap)
                    instance.default_swap_device = (
                        block_device.prepend_dev(diskswap.target_dev))

            if 'disk.config' in disk_mapping:
                diskconfig = self._get_guest_disk_config(instance,
                                                         'disk.config',
                                                         disk_mapping,
                                                         inst_type,
                                                         'raw')
                devices.append(diskconfig)

        for vol in block_device.get_bdms_to_connect(block_device_mapping,
                                                   mount_rootfs):
            connection_info = vol['connection_info']
            vol_dev = block_device.prepend_dev(vol['mount_device'])
            info = disk_mapping[vol_dev]
            self._connect_volume(connection_info, info)
            cfg = self._get_volume_config(connection_info, info)
            devices.append(cfg)
            vol['connection_info'] = connection_info
            vol.save(nova_context.get_admin_context())

        for d in devices:
            self._set_cache_mode(d)

        if (image_meta and
                image_meta.get('properties', {}).get('hw_scsi_model')):
            hw_scsi_model = image_meta['properties']['hw_scsi_model']
            scsi_controller = vconfig.LibvirtConfigGuestController()
            scsi_controller.type = 'scsi'
            scsi_controller.model = hw_scsi_model
            devices.append(scsi_controller)

        return devices

    def _get_host_sysinfo_serial_hardware(self):
        """Get a UUID from the host hardware

        Get a UUID for the host hardware reported by libvirt.
        This is typically from the SMBIOS data, unless it has
        been overridden in /etc/libvirt/libvirtd.conf
        """
        caps = self._get_host_capabilities()
        return caps.host.uuid

    def _get_host_sysinfo_serial_os(self):
        """Get a UUID from the host operating system

        Get a UUID for the host operating system. Modern Linux
        distros based on systemd provide a /etc/machine-id
        file containing a UUID. This is also provided inside
        systemd based containers and can be provided by other
        init systems too, since it is just a plain text file.
        """
        with open("/etc/machine-id") as f:
            # We want to have '-' in the right place
            # so we parse & reformat the value
            return str(uuid.UUID(f.read().split()[0]))

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
        sysinfo.system_uuid = instance['uuid']

        return sysinfo

    def _get_guest_pci_device(self, pci_device):

        dbsf = pci_utils.parse_address(pci_device['address'])
        dev = vconfig.LibvirtConfigGuestHostdevPCI()
        dev.domain, dev.bus, dev.slot, dev.function = dbsf

        # only kvm support managed mode
        if CONF.libvirt.virt_type in ('xen',):
            dev.managed = 'no'
        if CONF.libvirt.virt_type in ('kvm', 'qemu'):
            dev.managed = 'yes'

        return dev

    def _get_guest_config_meta(self, context, instance, flavor):
        """Get metadata config for guest."""

        meta = vconfig.LibvirtConfigGuestMetaNovaInstance()
        meta.package = version.version_string_with_package()
        meta.name = instance["display_name"]
        meta.creationTime = time.time()

        if instance["image_ref"] not in ("", None):
            meta.roottype = "image"
            meta.rootid = instance["image_ref"]

        if context is not None:
            ometa = vconfig.LibvirtConfigGuestMetaNovaOwner()
            ometa.userid = context.user_id
            ometa.username = context.user_name
            ometa.projectid = context.project_id
            ometa.projectname = context.project_name
            meta.owner = ometa

        fmeta = vconfig.LibvirtConfigGuestMetaNovaFlavor()
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

        if (image_meta is not None and image_meta.get('properties') and
               image_meta['properties'].get('hw_machine_type')
               is not None):
            mach_type = image_meta['properties']['hw_machine_type']
        else:
            # For ARM systems we will default to vexpress-a15 for armv7
            # and virt for aarch64
            if caps.host.cpu.arch == arch.ARMV7:
                mach_type = "vexpress-a15"

            if caps.host.cpu.arch == arch.AARCH64:
                mach_type = "virt"

            if caps.host.cpu.arch in (arch.S390, arch.S390X):
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
            LOG.warn(_LW("Too many id maps, only included first five."))
        for map_string in map_strings:
            try:
                idmap = klass()
                values = [int(i) for i in map_string.split(":")]
                idmap.start = values[0]
                idmap.target = values[1]
                idmap.count = values[2]
                idmaps.append(idmap)
            except (ValueError, IndexError):
                LOG.warn(_LW("Invalid value for id mapping %s"), map_string)
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

    def _get_cpu_numa_config_from_instance(self, instance_numa_topology):
        if instance_numa_topology:
            guest_cpu_numa = vconfig.LibvirtConfigGuestCPUNUMA()
            for instance_cell in instance_numa_topology.cells:
                guest_cell = vconfig.LibvirtConfigGuestCPUNUMACell()
                guest_cell.id = instance_cell.id
                guest_cell.cpus = instance_cell.cpuset
                guest_cell.memory = instance_cell.memory * units.Ki
                guest_cpu_numa.cells.append(guest_cell)
            return guest_cpu_numa

    def _get_guest_numa_config(self, instance_numa_topology, flavor,
                               allowed_cpus=None):
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
        topology = self._get_host_numa_topology()
        # We have instance NUMA so translate it to the config class
        guest_cpu_numa_config = self._get_cpu_numa_config_from_instance(
                instance_numa_topology)

        if not guest_cpu_numa_config:
            # No NUMA topology defined for instance
            vcpus = flavor.vcpus
            memory = flavor.memory_mb
            if topology:
                # Host is NUMA capable so try to keep the instance in a cell
                viable_cells_cpus = []
                for cell in topology.cells:
                    if vcpus <= len(cell.cpuset) and memory <= cell.memory:
                        viable_cells_cpus.append(cell.cpuset)

                if not viable_cells_cpus:
                    # We can't contain the instance in a cell - do nothing for
                    # now.
                    # TODO(ndipanov): Attempt to spread the instance across
                    # NUMA nodes and expose the topology to the instance as an
                    # optimisation
                    return GuestNumaConfig(allowed_cpus, None, None, None)
                else:
                    pin_cpuset = random.choice(viable_cells_cpus)
                    return GuestNumaConfig(pin_cpuset, None, None, None)
            else:
                # We have no NUMA topology in the host either
                return GuestNumaConfig(allowed_cpus, None, None, None)
        else:
            if topology:
                # Now get the CpuTune configuration from the numa_topology
                guest_cpu_tune = vconfig.LibvirtConfigGuestCPUTune()
                guest_numa_tune = vconfig.LibvirtConfigGuestNUMATune()
                allpcpus = []

                numa_mem = vconfig.LibvirtConfigGuestNUMATuneMemory()
                numa_memnodes = [vconfig.LibvirtConfigGuestNUMATuneMemNode()
                                 for _ in guest_cpu_numa_config.cells]

                for host_cell in topology.cells:
                    for guest_node_id, guest_config_cell in enumerate(
                            guest_cpu_numa_config.cells):
                        if guest_config_cell.id == host_cell.id:
                            node = numa_memnodes[guest_node_id]
                            node.cellid = guest_config_cell.id
                            node.nodeset = [host_cell.id]
                            node.mode = "strict"

                            numa_mem.nodeset.append(host_cell.id)

                            allpcpus.extend(host_cell.cpuset)

                            for cpu in guest_config_cell.cpus:
                                pin_cpuset = (
                                    vconfig.LibvirtConfigGuestCPUTuneVCPUPin())
                                pin_cpuset.id = cpu
                                pin_cpuset.cpuset = host_cell.cpuset
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
                # how to associate IO threads with guest devices to eliminiate
                # cross NUMA node traffic. This is an area of investigation
                # for QEMU community devs.
                emulatorpin = vconfig.LibvirtConfigGuestCPUTuneEmulatorPin()
                emulatorpin.cpuset = set(allpcpus)
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
            ret = vm_mode.EXE
        elif virt_type == "uml":
            ret = vm_mode.UML
        elif virt_type == "xen":
            ret = vm_mode.XEN
        else:
            ret = vm_mode.HVM
        return ret

    def _set_guest_for_rescue(self, rescue, guest, inst_path, virt_type,
                              root_device_name):
        if rescue.get('kernel_id'):
            guest.os_kernel = os.path.join(inst_path, "kernel.rescue")
            if virt_type == "xen":
                guest.os_cmdline = "ro root=%s" % root_device_name
            else:
                guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
                if virt_type == "qemu":
                    guest.os_cmdline += " no_timer_check"
        if rescue.get('ramdisk_id'):
            guest.os_initrd = os.path.join(inst_path, "ramdisk.rescue")

    def _set_guest_for_inst_kernel(self, instance, guest, inst_path, virt_type,
                                root_device_name, image_meta):
        guest.os_kernel = os.path.join(inst_path, "kernel")
        if virt_type == "xen":
            guest.os_cmdline = "ro root=%s" % root_device_name
        else:
            guest.os_cmdline = ("root=%s %s" % (root_device_name, CONSOLE))
            if virt_type == "qemu":
                guest.os_cmdline += " no_timer_check"
        if instance['ramdisk_id']:
            guest.os_initrd = os.path.join(inst_path, "ramdisk")
        # we only support os_command_line with images with an explicit
        # kernel set and don't want to break nova if there's an
        # os_command_line property without a specified kernel_id param
        if image_meta:
            img_props = image_meta.get('properties', {})
            if img_props.get('os_command_line'):
                guest.os_cmdline = img_props.get('os_command_line')

    def _set_clock(self, guest, os_type, image_meta, virt_type):
        # NOTE(mikal): Microsoft Windows expects the clock to be in
        # "localtime". If the clock is set to UTC, then you can use a
        # registry key to let windows know, but Microsoft says this is
        # buggy in http://support.microsoft.com/kb/2687252
        clk = vconfig.LibvirtConfigGuestClock()
        if os_type == 'windows':
            LOG.info(_LI('Configuring timezone for windows instance to '
                         'localtime'))
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
        if guestarch in (arch.I686, arch.X86_64):
            # NOTE(rfolco): HPET is a hardware timer for x86 arch.
            # qemu -no-hpet is not supported on non-x86 targets.
            tmhpet = vconfig.LibvirtConfigGuestTimer()
            tmhpet.name = "hpet"
            tmhpet.present = False
            clk.add_timer(tmhpet)

        # With new enough QEMU we can provide Windows guests
        # with the paravirtualized hyperv timer source. This
        # is the windows equiv of kvm-clock, allowing Windows
        # guests to accurately keep time.
        if (os_type == 'windows' and
            self._host.has_min_version(MIN_LIBVIRT_HYPERV_TIMER_VERSION,
                                       MIN_QEMU_HYPERV_TIMER_VERSION)):
            tmhyperv = vconfig.LibvirtConfigGuestTimer()
            tmhyperv.name = "hypervclock"
            tmhyperv.present = True
            clk.add_timer(tmhyperv)

    def _set_features(self, guest, os_type, caps, virt_type):
        if virt_type == "xen":
            # PAE only makes sense in X86
            if caps.host.cpu.arch in (arch.I686, arch.X86_64):
                guest.features.append(vconfig.LibvirtConfigGuestFeaturePAE())

        if virt_type not in ("lxc", "uml"):
            guest.features.append(vconfig.LibvirtConfigGuestFeatureACPI())
            guest.features.append(vconfig.LibvirtConfigGuestFeatureAPIC())

        if (virt_type in ("qemu", "kvm") and
                os_type == 'windows' and
                self._host.has_min_version(MIN_LIBVIRT_HYPERV_FEATURE_VERSION,
                                           MIN_QEMU_HYPERV_FEATURE_VERSION)):
            hv = vconfig.LibvirtConfigGuestFeatureHyperV()
            hv.relaxed = True

            if self._host.has_min_version(
                    MIN_LIBVIRT_HYPERV_FEATURE_EXTRA_VERSION):
                hv.spinlocks = True
                # Increase spinlock retries - value recommended by
                # KVM maintainers who certify Windows guests
                # with Microsoft
                hv.spinlock_retries = 8191
                hv.vapic = True
            guest.features.append(hv)

    def _create_serial_console_devices(self, guest, instance, flavor,
                                       image_meta):
        if CONF.serial_console.enabled:
            num_ports = hardware.get_number_of_serial_ports(
                flavor, image_meta)
            for port in six.moves.range(num_ports):
                console = vconfig.LibvirtConfigGuestSerial()
                console.port = port
                console.type = "tcp"
                console.listen_host = (
                    CONF.serial_console.proxyclient_address)
                console.listen_port = (
                    serial_console.acquire_port(
                        console.listen_host))
                guest.add_device(console)
        else:
            # The QEMU 'pty' driver throws away any data if no
            # client app is connected. Thus we can't get away
            # with a single type=pty console. Instead we have
            # to configure two separate consoles.
            if guest.cpu.arch in (arch.S390, arch.S390X):
                consolelog = vconfig.LibvirtConfigGuestConsole()
                consolelog.target_type = "sclplm"
            else:
                consolelog = vconfig.LibvirtConfigGuestSerial()
            consolelog.type = "file"
            consolelog.source_path = self._get_console_log_path(instance)
            guest.add_device(consolelog)

    def _add_video_driver(self, guest, image_meta, img_meta_prop, flavor):
        VALID_VIDEO_DEVICES = ("vga", "cirrus", "vmvga", "xen", "qxl")
        video = vconfig.LibvirtConfigGuestVideo()
        # NOTE(ldbragst): The following logic sets the video.type
        # depending on supported defaults given the architecture,
        # virtualization type, and features. The video.type attribute can
        # be overridden by the user with image_meta['properties'], which
        # is carried out in the next if statement below this one.
        guestarch = libvirt_utils.get_arch(image_meta)
        if guest.os_type == vm_mode.XEN:
            video.type = 'xen'
        elif guestarch in (arch.PPC, arch.PPC64):
            # NOTE(ldbragst): PowerKVM doesn't support 'cirrus' be default
            # so use 'vga' instead when running on Power hardware.
            video.type = 'vga'
        elif CONF.spice.enabled:
            video.type = 'qxl'
        if img_meta_prop.get('hw_video_model'):
            video.type = img_meta_prop.get('hw_video_model')
            if (video.type not in VALID_VIDEO_DEVICES):
                raise exception.InvalidVideoMode(model=video.type)

        # Set video memory, only if the flavor's limit is set
        video_ram = int(img_meta_prop.get('hw_video_ram', 0))
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
                          ("org.qemu.guest_agent.0", instance['name']))
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

    def _set_qemu_guest_agent(self, guest, flavor, instance, img_meta_prop):
        qga_enabled = False
        # Enable qga only if the 'hw_qemu_guest_agent' is equal to yes
        hw_qga = img_meta_prop.get('hw_qemu_guest_agent', 'no')
        if hw_qga.lower() == 'yes':
            LOG.debug("Qemu guest agent is enabled through image "
                      "metadata", instance=instance)
            qga_enabled = True
        if qga_enabled:
            self._add_qga_device(guest, instance)
        rng_is_virtio = img_meta_prop.get('hw_rng_model') == 'virtio'
        rng_allowed_str = flavor.extra_specs.get('hw_rng:allowed', '')
        rng_allowed = rng_allowed_str.lower() == 'true'
        if rng_is_virtio and rng_allowed:
            self._add_rng_device(guest, flavor)

    def _get_guest_memory_backing_config(self, inst_topology, numatune):
        host_topology = self._get_host_numa_topology()

        membacking = None
        if inst_topology and host_topology:
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
            if pages:
                membacking = vconfig.LibvirtConfigGuestMemoryBacking()
                membacking.hugepages = pages

        return membacking

    def _get_guest_config(self, instance, network_info, image_meta,
                          disk_info, rescue=None, block_device_info=None,
                          context=None, flavor=None):
        """Get config data for parameters.

        :param rescue: optional dictionary that should contain the key
            'ramdisk_id' if a ramdisk is needed for the rescue image and
            'kernel_id' if a kernel is needed for the rescue image.
        """
        ctxt = context or nova_context.get_admin_context()
        if flavor is None:
            with utils.temporary_mutation(ctxt, read_deleted="yes"):
                flavor = objects.Flavor.get_by_id(ctxt,
                                                  instance['instance_type_id'])
        inst_path = libvirt_utils.get_instance_path(instance)
        disk_mapping = disk_info['mapping']
        img_meta_prop = image_meta.get('properties', {}) if image_meta else {}

        virt_type = CONF.libvirt.virt_type
        guest = vconfig.LibvirtConfigGuest()
        guest.virt_type = virt_type
        guest.name = instance['name']
        guest.uuid = instance['uuid']
        # We are using default unit for memory: KiB
        guest.memory = flavor.memory_mb * units.Ki
        guest.vcpus = flavor.vcpus
        allowed_cpus = hardware.get_vcpu_pin_set()

        guest_numa_config = self._get_guest_numa_config(
                instance.numa_topology, flavor, allowed_cpus)

        guest.cpuset = guest_numa_config.cpuset
        guest.cputune = guest_numa_config.cputune
        guest.numatune = guest_numa_config.numatune

        guest.membacking = self._get_guest_memory_backing_config(
            instance.numa_topology, guest_numa_config.numatune)

        guest.metadata.append(self._get_guest_config_meta(context,
                                                          instance,
                                                          flavor))
        guest.idmaps = self._get_guest_idmaps()

        cputuning = ['shares', 'period', 'quota']
        for name in cputuning:
            key = "quota:cpu_" + name
            if key in flavor.extra_specs:
                if guest.cputune is None:
                    guest.cputune = vconfig.LibvirtConfigGuestCPUTune()
                setattr(guest.cputune, name,
                        int(flavor.extra_specs[key]))

        guest.cpu = self._get_guest_cpu_config(
                flavor, image_meta, guest_numa_config.numaconfig)

        if 'root' in disk_mapping:
            root_device_name = block_device.prepend_dev(
                disk_mapping['root']['dev'])
        else:
            root_device_name = None

        if root_device_name:
            # NOTE(yamahata):
            # for nova.api.ec2.cloud.CloudController.get_metadata()
            instance.root_device_name = root_device_name

        guest.os_type = vm_mode.get_from_instance(instance)

        if guest.os_type is None:
            guest.os_type = self._get_guest_os_type(virt_type)
        caps = self._get_host_capabilities()

        if virt_type == "xen":
            if guest.os_type == vm_mode.HVM:
                guest.os_loader = CONF.libvirt.xen_hvmloader_path

        if virt_type in ("kvm", "qemu"):
            if caps.host.cpu.arch in (arch.I686, arch.X86_64):
                guest.sysinfo = self._get_guest_config_sysinfo(instance)
                guest.os_smbios = vconfig.LibvirtConfigGuestSMBIOS()
            guest.os_mach_type = self._get_machine_type(image_meta, caps)

        if virt_type == "lxc":
            guest.os_init_path = "/sbin/init"
            guest.os_cmdline = CONSOLE
        elif virt_type == "uml":
            guest.os_kernel = "/usr/bin/linux"
            guest.os_root = root_device_name
        else:
            if rescue:
                self._set_guest_for_rescue(rescue, guest, inst_path, virt_type,
                                           root_device_name)
            elif instance['kernel_id']:
                self._set_guest_for_inst_kernel(instance, guest, inst_path,
                                                virt_type, root_device_name,
                                                image_meta)
            else:
                guest.os_boot_dev = blockinfo.get_boot_order(disk_info)

        self._set_features(guest, instance.os_type, caps, virt_type)
        self._set_clock(guest, instance.os_type, image_meta, virt_type)

        storage_configs = self._get_guest_storage_config(
                instance, image_meta, disk_info, rescue, block_device_info,
                flavor)
        for config in storage_configs:
            guest.add_device(config)

        for vif in network_info:
            config = self.vif_driver.get_config(
                instance, vif, image_meta,
                flavor, virt_type)
            guest.add_device(config)

        if virt_type in ("qemu", "kvm"):
            # Create the serial console char devices
            self._create_serial_console_devices(guest, instance, flavor,
                                                image_meta)
            if caps.host.cpu.arch in (arch.S390, arch.S390X):
                consolepty = vconfig.LibvirtConfigGuestConsole()
                consolepty.target_type = "sclp"
            else:
                consolepty = vconfig.LibvirtConfigGuestSerial()
        else:
            consolepty = vconfig.LibvirtConfigGuestConsole()

        consolepty.type = "pty"
        guest.add_device(consolepty)

        # We want a tablet if VNC is enabled, or SPICE is enabled and
        # the SPICE agent is disabled. If the SPICE agent is enabled
        # it provides a paravirt mouse which drastically reduces
        # overhead (by eliminating USB polling).
        #
        # NB: this implies that if both SPICE + VNC are enabled
        # at the same time, we'll get the tablet whether the
        # SPICE agent is used or not.
        need_usb_tablet = False
        if CONF.vnc_enabled:
            need_usb_tablet = CONF.libvirt.use_usb_tablet
        elif CONF.spice.enabled and not CONF.spice.agent_enabled:
            need_usb_tablet = CONF.libvirt.use_usb_tablet

        if need_usb_tablet and guest.os_type == vm_mode.HVM:
            tablet = vconfig.LibvirtConfigGuestInput()
            tablet.type = "tablet"
            tablet.bus = "usb"
            guest.add_device(tablet)

        if CONF.spice.enabled and CONF.spice.agent_enabled and \
                virt_type not in ('lxc', 'uml', 'xen'):
            channel = vconfig.LibvirtConfigGuestChannel()
            channel.target_name = "com.redhat.spice.0"
            guest.add_device(channel)

        # NB some versions of libvirt support both SPICE and VNC
        # at the same time. We're not trying to second guess which
        # those versions are. We'll just let libvirt report the
        # errors appropriately if the user enables both.
        add_video_driver = False
        if ((CONF.vnc_enabled and
             virt_type not in ('lxc', 'uml'))):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "vnc"
            graphics.keymap = CONF.vnc_keymap
            graphics.listen = CONF.vncserver_listen
            guest.add_device(graphics)
            add_video_driver = True

        if CONF.spice.enabled and \
                virt_type not in ('lxc', 'uml', 'xen'):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "spice"
            graphics.keymap = CONF.spice.keymap
            graphics.listen = CONF.spice.server_listen
            guest.add_device(graphics)
            add_video_driver = True

        if add_video_driver:
            self._add_video_driver(guest, image_meta, img_meta_prop, flavor)

        # Qemu guest agent only support 'qemu' and 'kvm' hypervisor
        if virt_type in ('qemu', 'kvm'):
            self._set_qemu_guest_agent(guest, flavor, instance, img_meta_prop)

        if virt_type in ('xen', 'qemu', 'kvm'):
            for pci_dev in pci_manager.get_instance_pci_devs(instance):
                guest.add_device(self._get_guest_pci_device(pci_dev))
        else:
            if len(pci_manager.get_instance_pci_devs(instance)) > 0:
                raise exception.PciDeviceUnsupportedHypervisor(
                    type=virt_type)

        if 'hw_watchdog_action' in flavor.extra_specs:
            LOG.warn(_LW('Old property name "hw_watchdog_action" is now '
                         'deprecated and will be removed in the next release. '
                         'Use updated property name '
                         '"hw:watchdog_action" instead'))
        # TODO(pkholkin): accepting old property name 'hw_watchdog_action'
        #                should be removed in the next release
        watchdog_action = (flavor.extra_specs.get('hw_watchdog_action') or
                           flavor.extra_specs.get('hw:watchdog_action')
                           or 'disabled')
        if (image_meta is not None and
                image_meta.get('properties', {}).get('hw_watchdog_action')):
            watchdog_action = image_meta['properties']['hw_watchdog_action']

        # NB(sross): currently only actually supported by KVM/QEmu
        if watchdog_action != 'disabled':
            if watchdog_actions.is_valid_watchdog_action(watchdog_action):
                bark = vconfig.LibvirtConfigGuestWatchdog()
                bark.action = watchdog_action
                guest.add_device(bark)
            else:
                raise exception.InvalidWatchdogAction(action=watchdog_action)

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

        return guest

    def _get_guest_xml(self, context, instance, network_info, disk_info,
                       image_meta=None, rescue=None,
                       block_device_info=None, write_to_disk=False,
                       flavor=None):

        if image_meta is None:
            image_ref = instance['image_ref']
            image_meta = compute_utils.get_image_metadata(
                                context, self._image_api, image_ref, instance)
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
                                      context, flavor=flavor)
        xml = conf.to_xml()

        if write_to_disk:
            instance_dir = libvirt_utils.get_instance_path(instance)
            xml_path = os.path.join(instance_dir, 'libvirt.xml')
            libvirt_utils.write_to_file(xml_path, xml)

        LOG.debug('End _get_guest_xml xml=%(xml)s',
                  {'xml': xml}, instance=instance)
        return xml

    def _get_domain(self, instance):
        """Retrieve libvirt domain object for an instance.

        :param instance: an nova.objects.Instance object

        Attempt to lookup the libvirt domain objects
        corresponding to the Nova instance, based on
        its name. If not found it will raise an
        exception.InstanceNotFound exception. On other
        errors, it will raise a exception.NovaException
        exception.

        :returns: a libvirt.Domain object
        """

        return self._lookup_by_name(instance.name)

    def _lookup_by_id(self, instance_id):
        """Retrieve libvirt domain object given an instance id.

        All libvirt error handling should be handled in this method and
        relevant nova exceptions should be raised in response.

        """
        try:
            return self._conn.lookupByID(instance_id)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance_id)

            msg = (_("Error from libvirt while looking up %(instance_id)s: "
                     "[Error Code %(error_code)s] %(ex)s")
                   % {'instance_id': instance_id,
                      'error_code': error_code,
                      'ex': ex})
            raise exception.NovaException(msg)

    def _lookup_by_name(self, instance_name):
        """Retrieve libvirt domain object given an instance name.

        All libvirt error handling should be handled in this method and
        relevant nova exceptions should be raised in response.

        """
        try:
            return self._conn.lookupByName(instance_name)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance_name)

            msg = (_('Error from libvirt while looking up %(instance_name)s: '
                     '[Error Code %(error_code)s] %(ex)s') %
                   {'instance_name': instance_name,
                    'error_code': error_code,
                    'ex': ex})
            raise exception.NovaException(msg)

    def get_info(self, instance):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        """
        virt_dom = self._get_domain(instance)
        try:
            dom_info = virt_dom.info()
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance['name'])

            msg = (_('Error from libvirt while getting domain info for '
                     '%(instance_name)s: [Error Code %(error_code)s] %(ex)s') %
                   {'instance_name': instance['name'],
                    'error_code': error_code,
                    'ex': ex})
            raise exception.NovaException(msg)

        return hardware.InstanceInfo(state=LIBVIRT_POWER_STATE[dom_info[0]],
                                     max_mem_kb=dom_info[1],
                                     mem_kb=dom_info[2],
                                     num_cpu=dom_info[3],
                                     cpu_time_ns=dom_info[4],
                                     id=virt_dom.ID())

    def _create_domain_setup_lxc(self, instance, block_device_info, disk_info):
        inst_path = libvirt_utils.get_instance_path(instance)
        block_device_mapping = driver.block_device_info_get_mapping(
                                                  block_device_info)
        disk_info = disk_info or {}
        disk_mapping = disk_info.get('mapping', [])

        if self._is_booted_from_volume(instance, disk_mapping):
            root_disk = block_device.get_root_bdm(block_device_mapping)
            disk_path = root_disk['connection_info']['data']['device_path']
            disk_info = blockinfo.get_info_from_bdm(
                                            CONF.libvirt.virt_type, root_disk)
            self._connect_volume(root_disk['connection_info'], disk_info)

            # Get the system metadata from the instance
            system_meta = utils.instance_sys_meta(instance)
            use_cow = system_meta['image_disk_format'] == 'qcow2'
        else:
            image = self.image_backend.image(instance, 'disk')
            disk_path = image.path
            use_cow = CONF.use_cow_images

        container_dir = os.path.join(inst_path, 'rootfs')
        fileutils.ensure_tree(container_dir)
        rootfs_dev = disk.setup_container(disk_path,
                                          container_dir=container_dir,
                                          use_cow=use_cow)

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
            disk.clean_lxc_namespace(container_dir=container_dir)
        else:
            disk.teardown_container(container_dir=container_dir)

    @contextlib.contextmanager
    def _lxc_disk_handler(self, instance, block_device_info, disk_info):
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

        self._create_domain_setup_lxc(instance, block_device_info, disk_info)

        try:
            yield
        finally:
            self._create_domain_cleanup_lxc(instance)

    def _create_domain(self, xml=None, domain=None,
                       instance=None, launch_flags=0, power_on=True):
        """Create a domain.

        Either domain or xml must be passed in. If both are passed, then
        the domain definition is overwritten from the xml.
        """
        err = None
        try:
            if xml:
                err = _LE('Error defining a domain with XML: %s') % xml
                domain = self._conn.defineXML(xml)

            if power_on:
                err = _LE('Error launching a defined domain with XML: %s') \
                          % encodeutils.safe_decode(domain.XMLDesc(0),
                                                    errors='ignore')
                domain.createWithFlags(launch_flags)

            if not utils.is_neutron():
                err = _LE('Error enabling hairpin mode with XML: %s') \
                          % encodeutils.safe_decode(domain.XMLDesc(0),
                                                    errors='ignore')
                self._enable_hairpin(domain.XMLDesc(0))
        except Exception:
            with excutils.save_and_reraise_exception():
                if err:
                    LOG.error(err)

        return domain

    def _neutron_failed_callback(self, event_name, instance):
        LOG.error(_LE('Neutron Reported failure on event '
                      '%(event)s for instance %(uuid)s'),
                  {'event': event_name, 'uuid': instance.uuid})
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

    def _create_domain_and_network(self, context, xml, instance, network_info,
                                   disk_info, block_device_info=None,
                                   power_on=True, reboot=False,
                                   vifs_already_plugged=False):

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

        launch_flags = events and libvirt.VIR_DOMAIN_START_PAUSED or 0
        domain = None
        try:
            with self.virtapi.wait_for_instance_event(
                    instance, events, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self.plug_vifs(instance, network_info)
                self.firewall_driver.setup_basic_filtering(instance,
                                                           network_info)
                self.firewall_driver.prepare_instance_filter(instance,
                                                             network_info)
                with self._lxc_disk_handler(instance, block_device_info,
                                            disk_info):
                    domain = self._create_domain(
                        xml, instance=instance,
                        launch_flags=launch_flags,
                        power_on=power_on)

                self.firewall_driver.apply_instance_filter(instance,
                                                           network_info)
        except exception.VirtualInterfaceCreateException:
            # Neutron reported failure and we didn't swallow it, so
            # bail here
            with excutils.save_and_reraise_exception():
                if domain:
                    domain.destroy()
                self.cleanup(context, instance, network_info=network_info,
                             block_device_info=block_device_info)
        except eventlet.timeout.Timeout:
            # We never heard from Neutron
            LOG.warn(_LW('Timeout waiting for vif plugging callback for '
                         'instance %(uuid)s'), {'uuid': instance['uuid']})
            if CONF.vif_plugging_is_fatal:
                if domain:
                    domain.destroy()
                self.cleanup(context, instance, network_info=network_info,
                             block_device_info=block_device_info)
                raise exception.VirtualInterfaceCreateException()

        # Resume only if domain has been paused
        if launch_flags & libvirt.VIR_DOMAIN_START_PAUSED:
            domain.resume()
        return domain

    def _get_all_block_devices(self):
        """Return all block devices in use on this node."""
        devices = []
        for dom in self._list_instance_domains():
            try:
                doc = etree.fromstring(dom.XMLDesc(0))
            except libvirt.libvirtError as e:
                LOG.warn(_LW("couldn't obtain the XML from domain:"
                             " %(uuid)s, exception: %(ex)s") %
                         {"uuid": dom.UUIDString(), "ex": e})
                continue
            except Exception:
                continue
            ret = doc.findall('./devices/disk')
            for node in ret:
                if node.get('type') != 'block':
                    continue
                for child in node.getchildren():
                    if child.tag == 'source':
                        devices.append(child.get('dev'))
        return devices

    def _get_interfaces(self, xml):
        """Note that this function takes a domain xml.

        Returns a list of all network interfaces for this instance.
        """
        doc = None

        try:
            doc = etree.fromstring(xml)
        except Exception:
            return []

        interfaces = []

        ret = doc.findall('./devices/interface')

        for node in ret:
            devdst = None

            for child in list(node):
                if child.tag == 'target':
                    devdst = child.attrib['dev']

            if devdst is None:
                continue

            interfaces.append(devdst)

        return interfaces

    def _get_vcpu_total(self):
        """Get available vcpu number of physical computer.

        :returns: the number of cpu core instances can be used.

        """
        if self._vcpu_total != 0:
            return self._vcpu_total

        try:
            total_pcpus = self._conn.getInfo()[2]
        except libvirt.libvirtError:
            LOG.warn(_LW("Cannot get the number of cpu, because this "
                         "function is not implemented for this platform. "))
            return 0

        if CONF.vcpu_pin_set is None:
            self._vcpu_total = total_pcpus
            return self._vcpu_total

        available_ids = hardware.get_vcpu_pin_set()
        if sorted(available_ids)[-1] >= total_pcpus:
            raise exception.Invalid(_("Invalid vcpu_pin_set config, "
                                      "out of hypervisor cpu range."))
        self._vcpu_total = len(available_ids)
        return self._vcpu_total

    def _get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.

        :returns: the total amount of memory(MB).

        """

        return self._conn.getInfo()[1]

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

        for (k, v) in info.iteritems():
            info[k] = v / units.Gi

        return info

    def _get_vcpu_used(self):
        """Get vcpu usage number of physical computer.

        :returns: The total number of vcpu(s) that are currently being used.

        """

        total = 0
        if CONF.libvirt.virt_type == 'lxc':
            return total + 1

        for dom in self._list_instance_domains():
            try:
                vcpus = dom.vcpus()
            except libvirt.libvirtError as e:
                LOG.warn(_LW("couldn't obtain the vpu count from domain id:"
                             " %(uuid)s, exception: %(ex)s") %
                         {"uuid": dom.UUIDString(), "ex": e})
            else:
                if vcpus is not None and len(vcpus) > 1:
                    total += len(vcpus[1])
            # NOTE(gtt116): give other tasks a chance.
            greenthread.sleep(0)
        return total

    def _get_memory_mb_used(self):
        """Get the used memory size(MB) of physical computer.

        :returns: the total usage of memory(MB).

        """

        if sys.platform.upper() not in ['LINUX2', 'LINUX3']:
            return 0

        with open('/proc/meminfo') as fp:
            m = fp.read().split()
        idx1 = m.index('MemFree:')
        idx2 = m.index('Buffers:')
        idx3 = m.index('Cached:')
        if CONF.libvirt.virt_type == 'xen':
            used = 0
            for dom in self._list_instance_domains(only_guests=False):
                try:
                    dom_mem = int(dom.info()[2])
                except libvirt.libvirtError as e:
                    LOG.warn(_LW("couldn't obtain the memory from domain:"
                                 " %(uuid)s, exception: %(ex)s") %
                             {"uuid": dom.UUIDString(), "ex": e})
                    continue
                # skip dom0
                if dom.ID() != 0:
                    used += dom_mem
                else:
                    # the mem reported by dom0 is be greater of what
                    # it is being used
                    used += (dom_mem -
                             (int(m[idx1 + 1]) +
                              int(m[idx2 + 1]) +
                              int(m[idx3 + 1])))
            # Convert it to MB
            return used / units.Ki
        else:
            avail = (int(m[idx1 + 1]) + int(m[idx2 + 1]) + int(m[idx3 + 1]))
            # Convert it to MB
            return self._get_memory_mb_total() - avail / units.Ki

    def _get_hypervisor_type(self):
        """Get hypervisor type.

        :returns: hypervisor type (ex. qemu)

        """

        return self._conn.getType()

    def _get_hypervisor_version(self):
        """Get hypervisor version.

        :returns: hypervisor version (ex. 12003)

        """

        # NOTE(justinsb): getVersion moved between libvirt versions
        # Trying to do be compatible with older versions is a lost cause
        # But ... we can at least give the user a nice message
        method = getattr(self._conn, 'getVersion', None)
        if method is None:
            raise exception.NovaException(_("libvirt version is too old"
                                    " (does not support getVersion)"))
            # NOTE(justinsb): If we wanted to get the version, we could:
            # method = getattr(libvirt, 'getVersion', None)
            # NOTE(justinsb): This would then rely on a proper version check

        return method()

    def _get_hypervisor_hostname(self):
        """Returns the hostname of the hypervisor."""
        hostname = self._conn.getHostname()
        if not hasattr(self, '_hypervisor_hostname'):
            self._hypervisor_hostname = hostname
        elif hostname != self._hypervisor_hostname:
            LOG.error(_LE('Hostname has changed from %(old)s '
                          'to %(new)s. A restart is required to take effect.'),
                          {'old': self._hypervisor_hostname,
                           'new': hostname})
        return self._hypervisor_hostname

    def _get_instance_capabilities(self):
        """Get hypervisor instance capabilities

        Returns a list of tuples that describe instances the
        hypervisor is capable of hosting.  Each tuple consists
        of the triplet (arch, hypervisor_type, vm_mode).

        :returns: List of tuples describing instance capabilities
        """
        caps = self._get_host_capabilities()
        instance_caps = list()
        for g in caps.guests:
            for dt in g.domtype:
                instance_cap = (
                    arch.canonicalize(g.arch),
                    hv_type.canonicalize(dt),
                    vm_mode.canonicalize(g.ostype))
                instance_caps.append(instance_cap)

        return instance_caps

    def _get_cpu_info(self):
        """Get cpuinfo information.

        Obtains cpu feature from virConnect.getCapabilities,
        and returns as a json string.

        :return: see above description

        """

        caps = self._get_host_capabilities()
        cpu_info = dict()

        cpu_info['arch'] = caps.host.cpu.arch
        cpu_info['model'] = caps.host.cpu.model
        cpu_info['vendor'] = caps.host.cpu.vendor

        topology = dict()
        topology['sockets'] = caps.host.cpu.sockets
        topology['cores'] = caps.host.cpu.cores
        topology['threads'] = caps.host.cpu.threads
        cpu_info['topology'] = topology

        features = list()
        for f in caps.host.cpu.features:
            features.append(f.name)
        cpu_info['features'] = features

        # TODO(berrange): why do we bother converting the
        # libvirt capabilities XML into a special JSON format ?
        # The data format is different across all the drivers
        # so we could just return the raw capabilities XML
        # which 'compare_cpu' could use directly
        #
        # That said, arch_filter.py now seems to rely on
        # the libvirt drivers format which suggests this
        # data format needs to be standardized across drivers
        return jsonutils.dumps(cpu_info)

    def _get_pcidev_info(self, devname):
        """Returns a dict of PCI device."""

        def _get_device_type(cfgdev):
            """Get a PCI device's device type.

            An assignable PCI device can be a normal PCI device,
            a SR-IOV Physical Function (PF), or a SR-IOV Virtual
            Function (VF). Only normal PCI devices or SR-IOV VFs
            are assignable, while SR-IOV PFs are always owned by
            hypervisor.

            Please notice that a PCI device with SR-IOV
            capability but not enabled is reported as normal PCI device.
            """
            for fun_cap in cfgdev.pci_capability.fun_capability:
                if len(fun_cap.device_addrs) != 0:
                    if fun_cap.type == 'virt_functions':
                        return {'dev_type': 'type-PF'}
                    if fun_cap.type == 'phys_function':
                        phys_address = "%04x:%02x:%02x.%01x" % (
                            fun_cap.device_addrs[0][0],
                            fun_cap.device_addrs[0][1],
                            fun_cap.device_addrs[0][2],
                            fun_cap.device_addrs[0][3])
                        return {'dev_type': 'type-VF',
                                'phys_function': phys_address}
            return {'dev_type': 'type-PCI'}

        virtdev = self._conn.nodeDeviceLookupByName(devname)
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

        # requirement by DataBase Model
        device['label'] = 'label_%(vendor_id)s_%(product_id)s' % device
        device.update(_get_device_type(cfgdev))
        return device

    def _get_pci_passthrough_devices(self):
        """Get host PCI devices information.

        Obtains pci devices information from libvirt, and returns
        as a JSON string.

        Each device information is a dictionary, with mandatory keys
        of 'address', 'vendor_id', 'product_id', 'dev_type', 'dev_id',
        'label' and other optional device specific information.

        Refer to the objects/pci_device.py for more idea of these keys.

        :returns: a JSON string containaing a list of the assignable PCI
                  devices information
        """
        # Bail early if we know we can't support `listDevices` to avoid
        # repeated warnings within a periodic task
        if not getattr(self, '_list_devices_supported', True):
            return jsonutils.dumps([])

        try:
            dev_names = self._conn.listDevices('pci', 0) or []
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                self._list_devices_supported = False
                LOG.warn(_LW("URI %(uri)s does not support "
                             "listDevices: " "%(error)s"),
                             {'uri': self.uri(), 'error': ex})
                return jsonutils.dumps([])
            else:
                raise

        pci_info = []
        for name in dev_names:
            pci_info.append(self._get_pcidev_info(name))

        return jsonutils.dumps(pci_info)

    def _get_host_numa_topology(self):
        if not self._host.has_min_version(MIN_LIBVIRT_NUMA_TOPOLOGY_VERSION):
            return

        caps = self._get_host_capabilities()
        topology = caps.host.topology

        if topology is None or not topology.cells:
            return

        topology = objects.NUMATopology(
                cells=[objects.NUMACell(
                    id=cell.id,
                    cpuset=set(cpu.id for cpu in cell.cpus),
                    memory=cell.memory / units.Ki,
                    cpu_usage=0, memory_usage=0,
                    mempages=[
                        objects.NUMAPagesTopology(
                            size_kb=pages.size,
                            total=pages.total,
                            used=0)
                        for pages in cell.mempages])
                for cell in topology.cells])

        allowed_cpus = hardware.get_vcpu_pin_set()
        if allowed_cpus:
            for cell in topology.cells:
                cell.cpuset &= allowed_cpus
        return topology

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.
        """
        vol_usage = []

        for instance_bdms in compute_host_bdms:
            instance = instance_bdms['instance']

            for bdm in instance_bdms['instance_bdms']:
                vol_stats = []
                mountpoint = bdm['device_name']
                if mountpoint.startswith('/dev/'):
                    mountpoint = mountpoint[5:]
                volume_id = bdm['volume_id']

                LOG.debug("Trying to get stats for the volume %s",
                          volume_id)
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
            domain = self._get_domain(instance)
            return domain.blockStats(disk_id)
        except libvirt.libvirtError as e:
            errcode = e.get_error_code()
            LOG.info(_LI('Getting block stats failed, device might have '
                         'been detached. Instance=%(instance_name)s '
                         'Disk=%(disk)s Code=%(errcode)s Error=%(e)s'),
                     {'instance_name': instance.name, 'disk': disk_id,
                      'errcode': errcode, 'e': e})
        except exception.InstanceNotFound:
            LOG.info(_LI('Could not find domain in libvirt for instance %s. '
                         'Cannot get block stats for device'), instance.name)

    def get_console_pool_info(self, console_type):
        # TODO(mdragon): console proxy should be implemented for libvirt,
        #                in case someone wants to use it with kvm or
        #                such. For now return fake data.
        return {'address': '127.0.0.1',
                'username': 'fakeuser',
                'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        self.firewall_driver.refresh_security_group_members(security_group_id)

    def refresh_instance_security_rules(self, instance):
        self.firewall_driver.refresh_instance_security_rules(instance)

    def refresh_provider_fw_rules(self):
        self.firewall_driver.refresh_provider_fw_rules()

    def get_available_resource(self, nodename):
        """Retrieve resource information.

        This method is called when nova-compute launches, and
        as part of a periodic task that records the results in the DB.

        :param nodename: will be put in PCI device
        :returns: dictionary containing resource info
        """

        disk_info_dict = self._get_local_gb_info()
        data = {}

        # NOTE(dprince): calling capabilities before getVersion works around
        # an initialization issue with some versions of Libvirt (1.0.5.5).
        # See: https://bugzilla.redhat.com/show_bug.cgi?id=1000116
        # See: https://bugs.launchpad.net/nova/+bug/1215593

        # Temporary convert supported_instances into a string, while keeping
        # the RPC version as JSON. Can be changed when RPC broadcast is removed
        data["supported_instances"] = jsonutils.dumps(
            self._get_instance_capabilities())

        data["vcpus"] = self._get_vcpu_total()
        data["memory_mb"] = self._get_memory_mb_total()
        data["local_gb"] = disk_info_dict['total']
        data["vcpus_used"] = self._get_vcpu_used()
        data["memory_mb_used"] = self._get_memory_mb_used()
        data["local_gb_used"] = disk_info_dict['used']
        data["hypervisor_type"] = self._get_hypervisor_type()
        data["hypervisor_version"] = self._get_hypervisor_version()
        data["hypervisor_hostname"] = self._get_hypervisor_hostname()
        data["cpu_info"] = self._get_cpu_info()

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
        :returns
            :tempfile: A dict containing the tempfile info on the destination
                       host
            :None: 1. If the instance path is not existing.
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
        :returns: a dict containing:
             :filename: name of the tmpfile under CONF.instances_path
             :block_migration: whether this is block migration
             :disk_over_commit: disk-over-commit factor on dest host
             :disk_available_mb: available disk space on dest host
        """
        disk_available_mb = None
        if block_migration:
            disk_available_gb = dst_compute_info['disk_available_least']
            disk_available_mb = \
                    (disk_available_gb * units.Ki) - CONF.reserved_host_disk_mb

        # Compare CPU
        source_cpu_info = src_compute_info['cpu_info']
        self._compare_cpu(source_cpu_info)

        # Create file on storage, to be checked on source host
        filename = self._create_shared_storage_test_file()

        return {"filename": filename,
                "image_type": CONF.libvirt.images_type,
                "block_migration": block_migration,
                "disk_over_commit": disk_over_commit,
                "disk_available_mb": disk_available_mb}

    def check_can_live_migrate_destination_cleanup(self, context,
                                                   dest_check_data):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param context: security context
        """
        filename = dest_check_data["filename"]
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
        :returns: a dict containing migration info
        """
        # Checking shared storage connectivity
        # if block migration, instances_paths should not be on shared storage.
        source = CONF.host

        dest_check_data.update({'is_shared_instance_path':
                self._check_shared_storage_test_file(
                    dest_check_data['filename'])})

        dest_check_data.update({'is_shared_block_storage':
                self._is_shared_block_storage(instance, dest_check_data,
                                              block_device_info)})

        if dest_check_data['block_migration']:
            if (dest_check_data['is_shared_block_storage'] or
                    dest_check_data['is_shared_instance_path']):
                reason = _("Block migration can not be used "
                           "with shared storage.")
                raise exception.InvalidLocalStorage(reason=reason, path=source)
            self._assert_dest_node_has_enough_disk(context, instance,
                                    dest_check_data['disk_available_mb'],
                                    dest_check_data['disk_over_commit'],
                                    block_device_info)

        elif not (dest_check_data['is_shared_block_storage'] or
                  dest_check_data['is_shared_instance_path']):
            reason = _("Live migration can not be used "
                       "without shared storage.")
            raise exception.InvalidSharedStorage(reason=reason, path=source)

        # NOTE(mikal): include the instance directory name here because it
        # doesn't yet exist on the destination but we want to force that
        # same name to be used
        instance_path = libvirt_utils.get_instance_path(instance,
                                                        relative=True)
        dest_check_data['instance_relative_path'] = instance_path

        # NOTE(danms): Emulate this old flag in case we're talking to
        # an older client (<= Juno). We can remove this when we bump the
        # compute RPC API to 4.0.
        dest_check_data['is_shared_storage'] = (
            dest_check_data['is_shared_instance_path'])

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
        if (CONF.libvirt.images_type == dest_check_data.get('image_type') and
                self.image_backend.backend().is_shared_block_storage()):
            # NOTE(dgenin): currently true only for RBD image backend
            return True

        if (dest_check_data.get('is_shared_instance_path') and
                self.image_backend.backend().is_file_in_instance_path()):
            # NOTE(angdraug): file based image backends (Raw, Qcow2)
            # place block device files under the instance path
            return True

        if (dest_check_data.get('is_volume_backed') and
                not bool(jsonutils.loads(
                    self.get_instance_disk_info(instance,
                                                block_device_info)))):
            return True

        return False

    def _assert_dest_node_has_enough_disk(self, context, instance,
                                             available_mb, disk_over_commit,
                                             block_device_info=None):
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

        ret = self.get_instance_disk_info(instance,
                                          block_device_info=block_device_info)
        disk_infos = jsonutils.loads(ret)

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
                      {'instance_uuid': instance['uuid'],
                       'available': available,
                       'necessary': necessary})
            raise exception.MigrationPreCheckError(reason=reason)

    def _compare_cpu(self, cpu_info):
        """Checks the host cpu is compatible to a cpu given by xml.
        "xml" must be a part of libvirt.openAuth(...).getCapabilities().
        return values follows by virCPUCompareResult.
        if 0 > return value, do live migration.
        'http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult'

        :param cpu_info: json string of cpu feature from _get_cpu_info()
        :returns:
            None. if given cpu info is not compatible to this server,
            raise exception.
        """

        # NOTE(berendt): virConnectCompareCPU not working for Xen
        if CONF.libvirt.virt_type == 'xen':
            return 1

        info = jsonutils.loads(cpu_info)
        LOG.info(_LI('Instance launched has CPU info: %s'), cpu_info)
        cpu = vconfig.LibvirtConfigCPU()
        cpu.arch = info['arch']
        cpu.model = info['model']
        cpu.vendor = info['vendor']
        cpu.sockets = info['topology']['sockets']
        cpu.cores = info['topology']['cores']
        cpu.threads = info['topology']['threads']
        for f in info['features']:
            cpu.add_feature(vconfig.LibvirtConfigCPUFeature(f))

        u = "http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult"
        m = _("CPU doesn't have compatibility.\n\n%(ret)s\n\nRefer to %(u)s")
        # unknown character exists in xml, then libvirt complains
        try:
            ret = self._conn.compareCPU(cpu.to_xml(), 0)
        except libvirt.libvirtError as e:
            with excutils.save_and_reraise_exception():
                LOG.error(m, {'ret': e, 'u': u})

        if ret <= 0:
            LOG.error(m, {'ret': ret, 'u': u})
            raise exception.InvalidCPUInfo(reason=m % {'ret': ret, 'u': u})

    def _create_shared_storage_test_file(self):
        """Makes tmpfile under CONF.instances_path."""
        dirpath = CONF.instances_path
        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug("Creating tmpfile %s to notify to other "
                  "compute nodes that they should mount "
                  "the same storage.", tmp_file)
        os.close(fd)
        return os.path.basename(tmp_file)

    def _check_shared_storage_test_file(self, filename):
        """Confirms existence of the tmpfile under CONF.instances_path.

        Cannot confirm tmpfile return False.
        """
        tmp_file = os.path.join(CONF.instances_path, filename)
        if not os.path.exists(tmp_file):
            return False
        else:
            return True

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
        timeout_count = range(CONF.live_migration_retry_count)
        while timeout_count:
            if self.firewall_driver.instance_filter_exists(instance,
                                                           network_info):
                break
            timeout_count.pop()
            if len(timeout_count) == 0:
                msg = _('The firewall filter for %s does not exist')
                raise exception.NovaException(msg % instance.name)
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
        :param migrate_data: implementation specific params

        """

        # 'dest' will be substituted into 'migration_uri' so ensure
        # it does't contain any characters that could be used to
        # exploit the URI accepted by libivrt
        if not libvirt_utils.is_valid_hostname(dest):
            raise exception.InvalidHostname(hostname=dest)

        greenthread.spawn(self._live_migration, context, instance, dest,
                          post_method, recover_method, block_migration,
                          migrate_data)

    def _correct_listen_addr(self, old_xml_str, listen_addrs):
        # NB(sross): can't just use LibvirtConfigGuest#parse_str
        #            here b/c it doesn't capture the entire XML
        #            description
        xml_doc = etree.fromstring(old_xml_str)

        # change over listen addresses
        for dev in xml_doc.findall('./devices/graphics'):
            gr_type = dev.get('type')
            listen_tag = dev.find('listen')
            if gr_type in ('vnc', 'spice'):
                if listen_tag is not None:
                    listen_tag.set('address', listen_addrs[gr_type])
                if dev.get('listen') is not None:
                    dev.set('listen', listen_addrs[gr_type])

        return etree.tostring(xml_doc)

    def _check_graphics_addresses_can_live_migrate(self, listen_addrs):
        LOCAL_ADDRS = ('0.0.0.0', '127.0.0.1', '::', '::1')

        local_vnc = CONF.vncserver_listen in LOCAL_ADDRS
        local_spice = CONF.spice.server_listen in LOCAL_ADDRS

        if ((CONF.vnc_enabled and not local_vnc) or
            (CONF.spice.enabled and not local_spice)):

            raise exception.MigrationError(
                    _('Your libvirt version does not support the'
                      ' VIR_DOMAIN_XML_MIGRATABLE flag or your'
                      ' destination node does not support'
                      ' retrieving listen addresses.  In order'
                      ' for live migration to work properly, you'
                      ' must configure the graphics (VNC and/or'
                      ' SPICE) listen addresses to be either'
                      ' the catch-all address (0.0.0.0 or ::) or'
                      ' the local address (127.0.0.1 or ::1).'))

        if listen_addrs is not None:
            dest_local_vnc = listen_addrs['vnc'] in LOCAL_ADDRS
            dest_local_spice = listen_addrs['spice'] in LOCAL_ADDRS

            if ((CONF.vnc_enabled and not dest_local_vnc) or
                (CONF.spice.enabled and not dest_local_spice)):

                LOG.warn(_('Your libvirt version does not support the'
                           ' VIR_DOMAIN_XML_MIGRATABLE flag, and the '
                           ' graphics (VNC and/or SPICE) listen'
                           ' addresses on the destination node do not'
                           ' match the addresses on the source node.'
                           ' Since the source node has listen'
                           ' addresses set to either the catch-all'
                           ' address (0.0.0.0 or ::) or the local'
                           ' address (127.0.0.1 or ::1), the live'
                           ' migration will succeed, but the VM will'
                           ' continue to listen on the current'
                           ' addresses.'))

    def _live_migration(self, context, instance, dest, post_method,
                        recover_method, block_migration=False,
                        migrate_data=None):
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
        :param migrate_data: implementation specific params
        """

        # Do live migration.
        try:
            if block_migration:
                flaglist = CONF.libvirt.block_migration_flag.split(',')
            else:
                flaglist = CONF.libvirt.live_migration_flag.split(',')
            flagvals = [getattr(libvirt, x.strip()) for x in flaglist]
            logical_sum = reduce(lambda x, y: x | y, flagvals)

            dom = self._get_domain(instance)

            pre_live_migrate_data = (migrate_data or {}).get(
                                        'pre_live_migration_result', {})
            listen_addrs = pre_live_migrate_data.get('graphics_listen_addrs')

            migratable_flag = getattr(libvirt, 'VIR_DOMAIN_XML_MIGRATABLE',
                                      None)

            if migratable_flag is None or listen_addrs is None:
                self._check_graphics_addresses_can_live_migrate(listen_addrs)
                dom.migrateToURI(CONF.libvirt.live_migration_uri % dest,
                                 logical_sum,
                                 None,
                                 CONF.libvirt.live_migration_bandwidth)
            else:
                old_xml_str = dom.XMLDesc(migratable_flag)
                new_xml_str = self._correct_listen_addr(old_xml_str,
                                                        listen_addrs)
                try:
                    dom.migrateToURI2(CONF.libvirt.live_migration_uri % dest,
                                      None,
                                      new_xml_str,
                                      logical_sum,
                                      None,
                                      CONF.libvirt.live_migration_bandwidth)
                except libvirt.libvirtError as ex:
                    # NOTE(mriedem): There is a bug in older versions of
                    # libvirt where the VIR_DOMAIN_XML_MIGRATABLE flag causes
                    # virDomainDefCheckABIStability to not compare the source
                    # and target domain xml's correctly for the CPU model.
                    # We try to handle that error here and attempt the legacy
                    # migrateToURI path, which could fail if the console
                    # addresses are not correct, but in that case we have the
                    # _check_graphics_addresses_can_live_migrate check in place
                    # to catch it.
                    # TODO(mriedem): Remove this workaround when
                    # Red Hat BZ #1141838 is closed.
                    error_code = ex.get_error_code()
                    if error_code == libvirt.VIR_ERR_CONFIG_UNSUPPORTED:
                        LOG.warn(_LW('An error occurred trying to live '
                                     'migrate. Falling back to legacy live '
                                     'migrate flow. Error: %s'), ex,
                                 instance=instance)
                        self._check_graphics_addresses_can_live_migrate(
                            listen_addrs)
                        dom.migrateToURI(
                            CONF.libvirt.live_migration_uri % dest,
                            logical_sum,
                            None,
                            CONF.libvirt.live_migration_bandwidth)
                    else:
                        raise

        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE("Live Migration failure: %s"), e,
                          instance=instance)
                recover_method(context, instance, dest, block_migration)

        # Waiting for completion of live_migration.
        timer = loopingcall.FixedIntervalLoopingCall(f=None)

        def wait_for_live_migration():
            """waiting for live migration completion."""
            try:
                self.get_info(instance).state
            except exception.InstanceNotFound:
                timer.stop()
                post_method(context, instance, dest, block_migration,
                            migrate_data)

        timer.f = wait_for_live_migration
        timer.start(interval=0.5).wait()

    def _fetch_instance_kernel_ramdisk(self, context, instance):
        """Download kernel and ramdisk for instance in instance directory."""
        instance_dir = libvirt_utils.get_instance_path(instance)
        if instance['kernel_id']:
            libvirt_utils.fetch_image(context,
                                      os.path.join(instance_dir, 'kernel'),
                                      instance['kernel_id'],
                                      instance['user_id'],
                                      instance['project_id'])
            if instance['ramdisk_id']:
                libvirt_utils.fetch_image(context,
                                          os.path.join(instance_dir,
                                                       'ramdisk'),
                                          instance['ramdisk_id'],
                                          instance['user_id'],
                                          instance['project_id'])

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        """Clean up destination node after a failed live migration."""
        self.destroy(context, instance, network_info, block_device_info,
                     destroy_disks, migrate_data)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data=None):
        """Preparation live migration."""
        # Steps for volume backed instance live migration w/o shared storage.
        is_shared_block_storage = True
        is_shared_instance_path = True
        is_block_migration = True
        instance_relative_path = None
        if migrate_data:
            is_shared_block_storage = migrate_data.get(
                    'is_shared_block_storage', True)
            is_shared_instance_path = migrate_data.get(
                    'is_shared_instance_path', True)
            is_block_migration = migrate_data.get('block_migration', True)
            instance_relative_path = migrate_data.get('instance_relative_path')

        if not (is_shared_instance_path and is_shared_block_storage):
            # NOTE(mikal): live migration of instances using config drive is
            # not supported because of a bug in libvirt (read only devices
            # are not copied by libvirt). See bug/1246201
            if configdrive.required_by(instance):
                raise exception.NoLiveMigrationForConfigDriveInLibVirt()

        if not is_shared_instance_path:
            # NOTE(mikal): this doesn't use libvirt_utils.get_instance_path
            # because we are ensuring that the same instance directory name
            # is used as was at the source
            if instance_relative_path:
                instance_dir = os.path.join(CONF.instances_path,
                                            instance_relative_path)
            else:
                instance_dir = libvirt_utils.get_instance_path(instance)

            if os.path.exists(instance_dir):
                raise exception.DestinationDiskExists(path=instance_dir)
            os.mkdir(instance_dir)

            if not is_shared_block_storage:
                # Ensure images and backing files are present.
                self._create_images_and_backing(context, instance,
                                                instance_dir, disk_info)

        if not (is_block_migration or is_shared_instance_path):
            # NOTE(angdraug): when block storage is shared between source and
            # destination and instance path isn't (e.g. volume backed or rbd
            # backed instance), instance path on destination has to be prepared

            # Touch the console.log file, required by libvirt.
            console_file = self._get_console_log_path(instance)
            libvirt_utils.file_open(console_file, 'a').close()

            # if image has kernel and ramdisk, just download
            # following normal way.
            self._fetch_instance_kernel_ramdisk(context, instance)

        # Establishing connection to volume server.
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_info = blockinfo.get_info_from_bdm(
                CONF.libvirt.virt_type, vol)
            self._connect_volume(connection_info, disk_info)

        # We call plug_vifs before the compute manager calls
        # ensure_filtering_rules_for_instance, to ensure bridge is set up
        # Retry operation is necessary because continuously request comes,
        # concurrent request occurs to iptables, then it complains.
        max_retry = CONF.live_migration_retry_count
        for cnt in range(max_retry):
            try:
                self.plug_vifs(instance, network_info)
                break
            except processutils.ProcessExecutionError:
                if cnt == max_retry - 1:
                    raise
                else:
                    LOG.warn(_LW('plug_vifs() failed %(cnt)d. Retry up to '
                                 '%(max_retry)d.'),
                             {'cnt': cnt,
                              'max_retry': max_retry},
                             instance=instance)
                    greenthread.sleep(1)

        res_data = {'graphics_listen_addrs': {}}
        res_data['graphics_listen_addrs']['vnc'] = CONF.vncserver_listen
        res_data['graphics_listen_addrs']['spice'] = CONF.spice.server_listen

        return res_data

    def _create_images_and_backing(self, context, instance, instance_dir,
                                   disk_info_json):
        """:param context: security context
           :param instance:
               nova.db.sqlalchemy.models.Instance object
               instance object that is migrated.
           :param instance_dir:
               instance path to use, calculated externally to handle block
               migrating an instance with an old style instance path
           :param disk_info_json:
               json strings specified in get_instance_disk_info

        """
        if not disk_info_json:
            disk_info = []
        else:
            disk_info = jsonutils.loads(disk_info_json)

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

                image = self.image_backend.image(instance,
                                                 instance_disk,
                                                 CONF.libvirt.images_type)
                if cache_name.startswith('ephemeral'):
                    image.cache(fetch_func=self._create_ephemeral,
                                fs_label=cache_name,
                                os_type=instance["os_type"],
                                filename=cache_name,
                                size=info['virt_disk_size'],
                                ephemeral_size=instance['ephemeral_gb'])
                elif cache_name.startswith('swap'):
                    inst_type = instance.get_flavor()
                    swap_mb = inst_type.swap
                    image.cache(fetch_func=self._create_swap,
                                filename="swap_%s" % swap_mb,
                                size=swap_mb * units.Mi,
                                swap_mb=swap_mb)
                else:
                    image.cache(fetch_func=libvirt_utils.fetch_image,
                                context=context,
                                filename=cache_name,
                                image_id=instance['image_ref'],
                                user_id=instance['user_id'],
                                project_id=instance['project_id'],
                                size=info['virt_disk_size'])

        # if image has kernel and ramdisk, just download
        # following normal way.
        self._fetch_instance_kernel_ramdisk(context, instance)

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        # Disconnect from volume server
        block_device_mapping = driver.block_device_info_get_mapping(
                block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device'].rpartition("/")[2]
            self._disconnect_volume(connection_info, disk_dev)

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
        # Define migrated instance, otherwise, suspend/destroy does not work.
        dom_list = self._conn.listDefinedDomains()
        if instance["name"] not in dom_list:
            # In case of block migration, destination does not have
            # libvirt.xml
            disk_info = blockinfo.get_disk_info(
                CONF.libvirt.virt_type, instance, block_device_info)
            xml = self._get_guest_xml(context, instance,
                                      network_info, disk_info,
                                      block_device_info=block_device_info,
                                      write_to_disk=True)
            self._conn.defineXML(xml)

    def _get_instance_disk_info(self, instance_name, xml,
                                block_device_info=None):
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        volume_devices = set()
        for vol in block_device_mapping:
            disk_dev = vol['mount_device'].rpartition("/")[2]
            volume_devices.add(disk_dev)

        disk_info = []
        doc = etree.fromstring(xml)
        disk_nodes = doc.findall('.//devices/disk')
        path_nodes = doc.findall('.//devices/disk/source')
        driver_nodes = doc.findall('.//devices/disk/driver')
        target_nodes = doc.findall('.//devices/disk/target')

        for cnt, path_node in enumerate(path_nodes):
            disk_type = disk_nodes[cnt].get('type')
            path = path_node.get('file') or path_node.get('dev')
            target = target_nodes[cnt].attrib['dev']

            if not path:
                LOG.debug('skipping disk for %s as it does not have a path',
                          instance_name)
                continue

            if disk_type not in ['file', 'block']:
                LOG.debug('skipping disk because it looks like a volume', path)
                continue

            if target in volume_devices:
                LOG.debug('skipping disk %(path)s (%(target)s) as it is a '
                          'volume', {'path': path, 'target': target})
                continue

            # get the real disk size or
            # raise a localized error if image is unavailable
            if disk_type == 'file':
                dk_size = int(os.path.getsize(path))
            elif disk_type == 'block':
                dk_size = lvm.get_volume_size(path)

            disk_type = driver_nodes[cnt].get('type')
            if disk_type == "qcow2":
                backing_file = libvirt_utils.get_disk_backing_file(path)
                virt_size = disk.get_disk_size(path)
                over_commit_size = int(virt_size) - dk_size
            else:
                backing_file = ""
                virt_size = dk_size
                over_commit_size = 0

            disk_info.append({'type': disk_type,
                              'path': path,
                              'virt_disk_size': virt_size,
                              'backing_file': backing_file,
                              'disk_size': dk_size,
                              'over_committed_disk_size': over_commit_size})
        return jsonutils.dumps(disk_info)

    def get_instance_disk_info(self, instance,
                               block_device_info=None):
        try:
            dom = self._get_domain(instance)
            xml = dom.XMLDesc(0)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            msg = (_('Error from libvirt while getting description of '
                     '%(instance_name)s: [Error Code %(error_code)s] '
                     '%(ex)s') %
                   {'instance_name': instance.name,
                    'error_code': error_code,
                    'ex': ex})
            LOG.warn(msg)
            raise exception.InstanceNotFound(instance_id=instance.name)

        return self._get_instance_disk_info(instance.name, xml,
                                            block_device_info)

    def _get_disk_over_committed_size_total(self):
        """Return total over committed disk size for all instances."""
        # Disk size that all instance uses : virtual_size - disk_size
        disk_over_committed_size = 0
        for dom in self._list_instance_domains():
            try:
                xml = dom.XMLDesc(0)
                disk_infos = jsonutils.loads(
                        self._get_instance_disk_info(dom.name(), xml))
                for info in disk_infos:
                    disk_over_committed_size += int(
                        info['over_committed_disk_size'])
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                LOG.warn(_LW(
                    'Error from libvirt while getting description of '
                    '%(instance_name)s: [Error Code %(error_code)s] %(ex)s'
                ) % {'instance_name': dom.name(),
                     'error_code': error_code,
                     'ex': ex})
            except OSError as e:
                if e.errno == errno.ENOENT:
                    LOG.warn(_LW('Periodic task is updating the host stat, '
                                 'it is trying to get disk %(i_name)s, '
                                 'but disk file was removed by concurrent '
                                 'operations such as resize.'),
                                {'i_name': dom.name()})
                elif e.errno == errno.EACCES:
                    LOG.warn(_LW('Periodic task is updating the host stat, '
                                 'it is trying to get disk %(i_name)s, '
                                 'but access is denied. It is most likely '
                                 'due to a VM that exists on the compute '
                                 'node but is not managed by Nova.'),
                             {'i_name': dom.name()})
                else:
                    raise
            except exception.VolumeBDMPathNotFound as e:
                LOG.warn(_LW('Periodic task is updating the host stats, '
                             'it is trying to get disk info for %(i_name)s, '
                             'but the backing volume block device was removed '
                             'by concurrent operations such as resize. '
                             'Error: %(error)s'),
                         {'i_name': dom.name(),
                          'error': e})
            # NOTE(gtt116): give other tasks a chance.
            greenthread.sleep(0)
        return disk_over_committed_size

    def unfilter_instance(self, instance, network_info):
        """See comments of same method in firewall_driver."""
        self.firewall_driver.unfilter_instance(instance,
                                               network_info=network_info)

    def get_available_nodes(self, refresh=False):
        return [self._get_hypervisor_hostname()]

    def get_host_cpu_stats(self):
        """Return the current CPU state of the host."""
        # Extract node's CPU statistics.
        stats = self._conn.getCPUStats(libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)
        # getInfo() returns various information about the host node
        # No. 3 is the expected CPU frequency.
        stats["frequency"] = self._conn.getInfo()[3]
        return stats

    def get_host_uptime(self, host):
        """Returns the result of calling "uptime"."""
        # NOTE(dprince): host seems to be ignored for this call and in
        # other compute drivers as well. Perhaps we should remove it?
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
                    utils.execute('ssh', dest, 'rm', '-rf', inst_base)
        except Exception:
            pass

    def _is_storage_shared_with(self, dest, inst_base):
        # NOTE (rmk): There are two methods of determining whether we are
        #             on the same filesystem: the source and dest IP are the
        #             same, or we create a file on the dest system via SSH
        #             and check whether the source system can also see it.
        shared_storage = (dest == self.get_host_ip_addr())
        if not shared_storage:
            tmp_file = uuid.uuid4().hex + '.tmp'
            tmp_path = os.path.join(inst_base, tmp_file)

            try:
                utils.execute('ssh', dest, 'touch', tmp_path)
                if os.path.exists(tmp_path):
                    shared_storage = True
                    os.unlink(tmp_path)
                else:
                    utils.execute('ssh', dest, 'rm', tmp_path)
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
        eph_size = block_device.get_bdm_ephemeral_disk_size(ephemerals)

        # Checks if the migration needs a disk resize down.
        if (flavor['root_gb'] < instance.root_gb or
            flavor['ephemeral_gb'] < eph_size):
            reason = _("Unable to resize disk down.")
            raise exception.InstanceFaultRollback(
                exception.ResizeError(reason=reason))

        disk_info_text = self.get_instance_disk_info(instance,
                block_device_info=block_device_info)
        disk_info = jsonutils.loads(disk_info_text)

        # NOTE(dgenin): Migration is not implemented for LVM backed instances.
        if (CONF.libvirt.images_type == 'lvm' and
                not self._is_booted_from_volume(instance, disk_info_text)):
            reason = _("Migration is not supported for LVM backed instances")
            raise exception.MigrationPreCheckError(reason=reason)

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
            utils.execute('ssh', dest, 'mkdir', '-p', inst_base)

        self.power_off(instance, timeout, retry_interval)

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device'].rpartition("/")[2]
            self._disconnect_volume(connection_info, disk_dev)

        try:
            utils.execute('mv', inst_base, inst_base_resize)
            # if we are migrating the instance with shared storage then
            # create the directory.  If it is a remote node the directory
            # has already been created
            if shared_storage:
                dest = None
                utils.execute('mkdir', '-p', inst_base)

            active_flavor = instance.get_flavor()
            for info in disk_info:
                # assume inst_base == dirname(info['path'])
                img_path = info['path']
                fname = os.path.basename(img_path)
                from_path = os.path.join(inst_base_resize, fname)

                if (fname == 'disk.swap' and
                    active_flavor.get('swap', 0) != flavor.get('swap', 0)):
                    # To properly resize the swap partition, it must be
                    # re-created with the proper size.  This is acceptable
                    # because when an OS is shut down, the contents of the
                    # swap space are just garbage, the OS doesn't bother about
                    # what is in it.

                    # We will not copy over the swap disk here, and rely on
                    # finish_migration/_create_image to re-create it for us.
                    continue

                if info['type'] == 'qcow2' and info['backing_file']:
                    tmp_path = from_path + "_rbase"
                    # merge backing file
                    utils.execute('qemu-img', 'convert', '-f', 'qcow2',
                                  '-O', 'qcow2', from_path, tmp_path)

                    if shared_storage:
                        utils.execute('mv', tmp_path, img_path)
                    else:
                        libvirt_utils.copy_image(tmp_path, img_path, host=dest)
                        utils.execute('rm', '-f', tmp_path)

                else:  # raw or qcow2 with no backing file
                    libvirt_utils.copy_image(from_path, img_path, host=dest)
        except Exception:
            with excutils.save_and_reraise_exception():
                self._cleanup_remote_migration(dest, inst_base,
                                               inst_base_resize,
                                               shared_storage)

        return disk_info_text

    def _wait_for_running(self, instance):
        state = self.get_info(instance).state

        if state == power_state.RUNNING:
            LOG.info(_LI("Instance running successfully."), instance=instance)
            raise loopingcall.LoopingCallDone()

    @staticmethod
    def _disk_size_from_instance(instance, info):
        """Determines the disk size from instance properties

        Returns the disk size by using the disk name to determine whether it
        is a root or an ephemeral disk, then by checking properties of the
        instance returns the size converted to bytes.

        Returns 0 if the disk name not match (disk, disk.local).
        """
        fname = os.path.basename(info['path'])
        if fname == 'disk':
            size = instance['root_gb']
        elif fname == 'disk.local':
            size = instance['ephemeral_gb']
        else:
            size = 0
        return size * units.Gi

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

    def _disk_resize(self, info, size):
        """Attempts to resize a disk to size

        Attempts to resize a disk by checking the capabilities and
        preparing the format, then calling disk.api.extend.

        Note: Currently only support disk extend.
        """
        # If we have a non partitioned image that we can extend
        # then ensure we're in 'raw' format so we can extend file system.
        fmt, org = [info['type']] * 2
        pth = info['path']
        if (size and fmt == 'qcow2' and
                disk.can_resize_image(pth, size) and
                disk.is_image_partitionless(pth, use_cow=True)):
            self._disk_qcow2_to_raw(pth)
            fmt = 'raw'

        if size:
            use_cow = fmt == 'qcow2'
            disk.extend(pth, size, use_cow=use_cow)

        if fmt != org:
            # back to qcow2 (no backing_file though) so that snapshot
            # will be available
            self._disk_raw_to_qcow2(pth)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        LOG.debug("Starting finish_migration", instance=instance)

        # resize disks. only "disk" and "disk.local" are necessary.
        disk_info = jsonutils.loads(disk_info)
        for info in disk_info:
            size = self._disk_size_from_instance(instance, info)
            if resize_instance:
                self._disk_resize(info, size)
            if info['type'] == 'raw' and CONF.use_cow_images:
                self._disk_raw_to_qcow2(info['path'])

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        # assume _create_image do nothing if a target file exists.
        self._create_image(context, instance, disk_info['mapping'],
                           network_info=network_info,
                           block_device_info=None, inject_files=False)
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  block_device_info=block_device_info,
                                  write_to_disk=True)
        self._create_domain_and_network(context, xml, instance, network_info,
                                        disk_info,
                                        block_device_info=block_device_info,
                                        power_on=power_on,
                                        vifs_already_plugged=True)
        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

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

        image_ref = instance.get('image_ref')
        image_meta = compute_utils.get_image_metadata(context,
                                                      self._image_api,
                                                      image_ref,
                                                      instance)

        disk_info = blockinfo.get_disk_info(CONF.libvirt.virt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        xml = self._get_guest_xml(context, instance, network_info, disk_info,
                                  block_device_info=block_device_info)
        self._create_domain_and_network(context, xml, instance, network_info,
                                        disk_info,
                                        block_device_info=block_device_info,
                                        power_on=power_on)

        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._cleanup_resize(instance, network_info)

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
        domain = self._get_domain(instance)
        output = {}
        # get cpu time, might launch an exception if the method
        # is not supported by the underlying hypervisor being
        # used by libvirt
        try:
            cputime = domain.vcpus()[0]
            for i in range(len(cputime)):
                output["cpu" + str(i) + "_time"] = cputime[i][2]
        except libvirt.libvirtError:
            pass
        # get io status
        xml = domain.XMLDesc(0)
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
        domain = self._get_domain(instance)
        xml = domain.XMLDesc(0)
        xml_doc = etree.fromstring(xml)

        (state, max_mem, mem, num_cpu, cpu_time) = domain.info()
        config_drive = configdrive.required_by(instance)
        launched_at = timeutils.normalize_time(instance['launched_at'])
        uptime = timeutils.delta_seconds(launched_at,
                                         timeutils.utcnow())
        diags = diagnostics.Diagnostics(state=power_state.STATE_MAP[state],
                                        driver='libvirt',
                                        config_drive=config_drive,
                                        hypervisor_os='linux',
                                        uptime=uptime)
        diags.memory_details.maximum = max_mem / units.Mi
        diags.memory_details.used = mem / units.Mi

        # get cpu time, might launch an exception if the method
        # is not supported by the underlying hypervisor being
        # used by libvirt
        try:
            cputime = domain.vcpus()[0]
            num_cpus = len(cputime)
            for i in range(num_cpus):
                diags.add_cpu(time=cputime[i][2])
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
                               write_requests=stats[2])
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
        if len(diags.nic_details) > 0:
            ret = xml_doc.findall('./devices/interface')
            index = 0
            for node in ret:
                for child in node.getchildren():
                    if child.tag == 'mac':
                        diags.nic_details[index].mac_address = child.get(
                            'address')
        return diags

    def instance_on_disk(self, instance):
        # ensure directories exist and are writable
        instance_path = libvirt_utils.get_instance_path(instance)
        LOG.debug('Checking instance files accessibility %s', instance_path)
        shared_instance_path = os.access(instance_path, os.W_OK)
        # NOTE(flwang): For shared block storage scenario, the file system is
        # not really shared by the two hosts, but the volume of evacuated
        # instance is reachable.
        shared_block_storage = (self.image_backend.backend().
                                is_shared_block_storage())
        return shared_instance_path or shared_block_storage

    def inject_network_info(self, instance, nw_info):
        self.firewall_driver.setup_basic_filtering(instance, nw_info)

    def _delete_instance_files(self, instance):
        # NOTE(mikal): a shim to handle this file not using instance objects
        # everywhere. Remove this when that conversion happens.
        context = nova_context.get_admin_context(read_deleted='yes')
        inst_obj = objects.Instance.get_by_uuid(context, instance['uuid'])

        # NOTE(mikal): this code should be pushed up a layer when this shim is
        # removed.
        attempts = int(inst_obj.system_metadata.get('clean_attempts', '0'))
        success = self.delete_instance_files(inst_obj)
        inst_obj.system_metadata['clean_attempts'] = str(attempts + 1)
        if success:
            inst_obj.cleaned = True
        inst_obj.save(context)

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
        for i in six.moves.range(2):
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
            LOG.info(_LI('Deleting instance files %s'), target_del,
                     instance=instance)
            remaining_path = target_del
            try:
                shutil.rmtree(target_del)
            except OSError as e:
                LOG.error(_LE('Failed to cleanup directory %(target)s: '
                              '%(e)s'), {'target': target_del, 'e': e},
                            instance=instance)

        # It is possible that the delete failed, if so don't mark the instance
        # as cleaned.
        if remaining_path and os.path.exists(remaining_path):
            LOG.info(_LI('Deletion of %s failed'), remaining_path,
                     instance=instance)
            return False

        LOG.info(_LI('Deletion of %s complete'), target_del, instance=instance)
        return True

    @property
    def need_legacy_block_device_info(self):
        return False

    def default_root_device_name(self, instance, image_meta, root_bdm):

        disk_bus = blockinfo.get_disk_bus_for_device_type(
            CONF.libvirt.virt_type, image_meta, "disk")
        cdrom_bus = blockinfo.get_disk_bus_for_device_type(
            CONF.libvirt.virt_type, image_meta, "cdrom")
        root_info = blockinfo.get_root_info(
            CONF.libvirt.virt_type, image_meta, root_bdm, disk_bus,
            cdrom_bus)
        return block_device.prepend_dev(root_info['dev'])

    def default_device_names_for_instance(self, instance, root_device_name,
                                          *block_device_lists):
        ephemerals, swap, block_device_mapping = block_device_lists[:3]

        blockinfo.default_device_names(CONF.libvirt.virt_type,
                                       nova_context.get_admin_context(),
                                       instance, root_device_name,
                                       ephemerals, swap,
                                       block_device_mapping)

    def is_supported_fs_format(self, fs_type):
        return fs_type in [disk.FS_FORMAT_EXT2, disk.FS_FORMAT_EXT3,
                           disk.FS_FORMAT_EXT4, disk.FS_FORMAT_XFS]
