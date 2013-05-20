# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

**Related Flags**

:libvirt_type:  Libvirt domain type.  Can be kvm, qemu, uml, xen
                (default: kvm).
:libvirt_uri:  Override for the default libvirt URI (depends on libvirt_type).
:libvirt_disk_prefix:  Override the default disk prefix for the devices
                       attached to a server.
:rescue_image_id:  Rescue ami image (None = original image).
:rescue_kernel_id:  Rescue aki image (None = original image).
:rescue_ramdisk_id:  Rescue ari image (None = original image).
:injected_network_template:  Template file for injected network
:allow_same_net_traffic:  Whether to allow in project network traffic

"""

import errno
import eventlet
import functools
import glob
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import uuid

from eventlet import greenio
from eventlet import greenthread
from eventlet import patcher
from eventlet import tpool
from eventlet import util as eventlet_util
from lxml import etree
from oslo.config import cfg
from xml.dom import minidom

from nova.api.metadata import base as instance_metadata
from nova import block_device
from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_mode
from nova import context as nova_context
from nova import exception
from nova.image import glance
from nova.openstack.common import excutils
from nova.openstack.common import fileutils
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common.notifier import api as notifier
from nova.openstack.common import processutils
from nova import utils
from nova import version
from nova.virt import configdrive
from nova.virt.disk import api as disk
from nova.virt import driver
from nova.virt import event as virtevent
from nova.virt import firewall
from nova.virt.libvirt import blockinfo
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import firewall as libvirt_firewall
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import imagecache
from nova.virt.libvirt import utils as libvirt_utils
from nova.virt import netutils

native_threading = patcher.original("threading")
native_Queue = patcher.original("Queue")

libvirt = None

LOG = logging.getLogger(__name__)

libvirt_opts = [
    cfg.StrOpt('rescue_image_id',
               default=None,
               help='Rescue ami image'),
    cfg.StrOpt('rescue_kernel_id',
               default=None,
               help='Rescue aki image'),
    cfg.StrOpt('rescue_ramdisk_id',
               default=None,
               help='Rescue ari image'),
    cfg.StrOpt('libvirt_type',
               default='kvm',
               help='Libvirt domain type (valid options are: '
                    'kvm, lxc, qemu, uml, xen)'),
    cfg.StrOpt('libvirt_uri',
               default='',
               help='Override the default libvirt URI '
                    '(which is dependent on libvirt_type)'),
    cfg.BoolOpt('libvirt_inject_password',
                default=False,
                help='Inject the admin password at boot time, '
                     'without an agent.'),
    cfg.BoolOpt('libvirt_inject_key',
                default=True,
                help='Inject the ssh public key at boot time'),
    cfg.IntOpt('libvirt_inject_partition',
                default=1,
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
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER',
               help='Migration flags to be set for live migration'),
    cfg.StrOpt('block_migration_flag',
               default='VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER, '
                       'VIR_MIGRATE_NON_SHARED_INC',
               help='Migration flags to be set for block migration'),
    cfg.IntOpt('live_migration_bandwidth',
               default=0,
               help='Maximum bandwidth to be used during migration, in Mbps'),
    cfg.StrOpt('snapshot_image_format',
               default=None,
               help='Snapshot image format (valid options are : '
                    'raw, qcow2, vmdk, vdi). '
                    'Defaults to same as source image'),
    cfg.StrOpt('libvirt_vif_driver',
               default='nova.virt.libvirt.vif.LibvirtGenericVIFDriver',
               help='The libvirt VIF driver to configure the VIFs.'),
    cfg.ListOpt('libvirt_volume_drivers',
                default=[
                  'iscsi=nova.virt.libvirt.volume.LibvirtISCSIVolumeDriver',
                  'local=nova.virt.libvirt.volume.LibvirtVolumeDriver',
                  'fake=nova.virt.libvirt.volume.LibvirtFakeVolumeDriver',
                  'rbd=nova.virt.libvirt.volume.LibvirtNetVolumeDriver',
                  'sheepdog=nova.virt.libvirt.volume.LibvirtNetVolumeDriver',
                  'nfs=nova.virt.libvirt.volume.LibvirtNFSVolumeDriver',
                  'aoe=nova.virt.libvirt.volume.LibvirtAOEVolumeDriver',
                  'glusterfs='
                      'nova.virt.libvirt.volume.LibvirtGlusterfsVolumeDriver',
                  'fibre_channel=nova.virt.libvirt.volume.'
                      'LibvirtFibreChannelVolumeDriver',
                  'scality='
                      'nova.virt.libvirt.volume.LibvirtScalityVolumeDriver',
                  ],
                help='Libvirt handlers for remote volumes.'),
    cfg.StrOpt('libvirt_disk_prefix',
               default=None,
               help='Override the default disk prefix for the devices attached'
                    ' to a server, which is dependent on libvirt_type. '
                    '(valid options are: sd, xvd, uvd, vd)'),
    cfg.IntOpt('libvirt_wait_soft_reboot_seconds',
               default=120,
               help='Number of seconds to wait for instance to shut down after'
                    ' soft reboot request is made. We fall back to hard reboot'
                    ' if instance does not shutdown within this window.'),
    cfg.BoolOpt('libvirt_nonblocking',
                default=True,
                help='Use a separated OS thread pool to realize non-blocking'
                     ' libvirt calls'),
    cfg.StrOpt('libvirt_cpu_mode',
               default=None,
               help='Set to "host-model" to clone the host CPU feature flags; '
                    'to "host-passthrough" to use the host CPU model exactly; '
                    'to "custom" to use a named CPU model; '
                    'to "none" to not set any CPU model. '
                    'If libvirt_type="kvm|qemu", it will default to '
                    '"host-model", otherwise it will default to "none"'),
    cfg.StrOpt('libvirt_cpu_model',
               default=None,
               help='Set to a named libvirt CPU model (see names listed '
                    'in /usr/share/libvirt/cpu_map.xml). Only has effect if '
                    'libvirt_cpu_mode="custom" and libvirt_type="kvm|qemu"'),
    cfg.StrOpt('libvirt_snapshots_directory',
               default='$instances_path/snapshots',
               help='Location where libvirt driver will store snapshots '
                    'before uploading them to image service'),
    cfg.StrOpt('xen_hvmloader_path',
                default='/usr/lib/xen/boot/hvmloader',
                help='Location where the Xen hvmloader is kept'),
    cfg.ListOpt('disk_cachemodes',
                 default=[],
                 help='Specific cachemodes to use for different disk types '
                      'e.g: ["file=directsync","block=none"]'),
    cfg.StrOpt('vcpu_pin_set',
                default=None,
                help='Which pcpus can be used by vcpus of instance '
                     'e.g: "4-12,^8,15"'),
    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts)
CONF.import_opt('host', 'nova.netconf')
CONF.import_opt('my_ip', 'nova.netconf')
CONF.import_opt('default_ephemeral_format', 'nova.virt.driver')
CONF.import_opt('use_cow_images', 'nova.virt.driver')
CONF.import_opt('live_migration_retry_count', 'nova.compute.manager')
CONF.import_opt('vncserver_proxyclient_address', 'nova.vnc')
CONF.import_opt('server_proxyclient_address', 'nova.spice', group='spice')

DEFAULT_FIREWALL_DRIVER = "%s.%s" % (
    libvirt_firewall.__name__,
    libvirt_firewall.IptablesFirewallDriver.__name__)

MAX_CONSOLE_BYTES = 102400


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

MIN_LIBVIRT_VERSION = (0, 9, 6)
# When the above version matches/exceeds this version
# delete it & corresponding code using it
MIN_LIBVIRT_HOST_CPU_VERSION = (0, 9, 10)
MIN_LIBVIRT_CLOSE_CALLBACK_VERSION = (1, 0, 1)
# Live snapshot requirements
REQ_HYPERVISOR_LIVESNAPSHOT = "QEMU"
MIN_LIBVIRT_LIVESNAPSHOT_VERSION = (1, 0, 0)
MIN_QEMU_LIVESNAPSHOT_VERSION = (1, 3, 0)


def libvirt_error_handler(ctxt, err):
    # Just ignore instead of default outputting to stderr.
    pass


class LibvirtDriver(driver.ComputeDriver):

    capabilities = {
        "has_imagecache": True,
        "supports_recreate": True,
        }

    def __init__(self, virtapi, read_only=False):
        super(LibvirtDriver, self).__init__(virtapi)

        global libvirt
        if libvirt is None:
            libvirt = __import__('libvirt')

        self._host_state = None
        self._initiator = None
        self._fc_wwnns = None
        self._fc_wwpns = None
        self._wrapped_conn = None
        self._wrapped_conn_lock = threading.Lock()
        self._caps = None
        self._vcpu_total = 0
        self.read_only = read_only
        self.firewall_driver = firewall.load_driver(
            DEFAULT_FIREWALL_DRIVER,
            self.virtapi,
            get_connection=self._get_connection)

        vif_class = importutils.import_class(CONF.libvirt_vif_driver)
        self.vif_driver = vif_class(self._get_connection)

        self.volume_drivers = driver.driver_dict_from_config(
            CONF.libvirt_volume_drivers, self)

        self._host_state = None
        self._event_queue = None

        self._disk_cachemode = None
        self.image_cache_manager = imagecache.ImageCacheManager()
        self.image_backend = imagebackend.Backend(CONF.use_cow_images)

        self.disk_cachemodes = {}

        self.valid_cachemodes = ["default",
                                 "none",
                                 "writethrough",
                                 "writeback",
                                 "directsync",
                                 "writethrough",
                                 "unsafe",
                                ]

        for mode_str in CONF.disk_cachemodes:
            disk_type, sep, cache_mode = mode_str.partition('=')
            if cache_mode not in self.valid_cachemodes:
                LOG.warn(_("Invalid cachemode %(cache_mode)s specified "
                           "for disk type %(disk_type)s.") % locals())
                continue
            self.disk_cachemodes[disk_type] = cache_mode

    @property
    def disk_cachemode(self):
        if self._disk_cachemode is None:
            # We prefer 'none' for consistent performance, host crash
            # safety & migration correctness by avoiding host page cache.
            # Some filesystems (eg GlusterFS via FUSE) don't support
            # O_DIRECT though. For those we fallback to 'writethrough'
            # which gives host crash safety, and is safe for migration
            # provided the filesystem is cache coherant (cluster filesystems
            # typically are, but things like NFS are not).
            self._disk_cachemode = "none"
            if not self._supports_direct_io(CONF.instances_path):
                self._disk_cachemode = "writethrough"
        return self._disk_cachemode

    @property
    def host_state(self):
        if not self._host_state:
            self._host_state = HostState(self)
        return self._host_state

    def set_cache_mode(self, conf):
        """Set cache mode on LibvirtConfigGuestDisk object."""
        try:
            source_type = conf.source_type
            driver_cache = conf.driver_cache
        except AttributeError:
            return

        cache_mode = self.disk_cachemodes.get(source_type,
                                              driver_cache)
        conf.driver_cache = cache_mode

    def has_min_version(self, lv_ver=None, hv_ver=None, hv_type=None):
        def _munge_version(ver):
            return ver[0] * 1000000 + ver[1] * 1000 + ver[2]

        try:
            if lv_ver is not None:
                libvirt_version = self._conn.getLibVersion()
                if libvirt_version < _munge_version(lv_ver):
                    return False

            if hv_ver is not None:
                hypervisor_version = self._conn.getVersion()
                if hypervisor_version < _munge_version(hv_ver):
                    return False

            if hv_type is not None:
                hypervisor_type = self._conn.getType()
                if hypervisor_type != hv_type:
                    return False

            return True
        except Exception:
            return False

    def _native_thread(self):
        """Receives async events coming in from libvirtd.

        This is a native thread which runs the default
        libvirt event loop implementation. This processes
        any incoming async events from libvirtd and queues
        them for later dispatch. This thread is only
        permitted to use libvirt python APIs, and the
        driver.queue_event method. In particular any use
        of logging is forbidden, since it will confuse
        eventlet's greenthread integration
        """

        while True:
            libvirt.virEventRunDefaultImpl()

    def _dispatch_thread(self):
        """Dispatches async events coming in from libvirtd.

        This is a green thread which waits for events to
        arrive from the libvirt event loop thread. This
        then dispatches the events to the compute manager.
        """

        while True:
            self._dispatch_events()

    @staticmethod
    def _event_lifecycle_callback(conn, dom, event, detail, opaque):
        """Receives lifecycle events from libvirt.

        NB: this method is executing in a native thread, not
        an eventlet coroutine. It can only invoke other libvirt
        APIs, or use self.queue_event(). Any use of logging APIs
        in particular is forbidden.
        """

        self = opaque

        uuid = dom.UUIDString()
        transition = None
        if event == libvirt.VIR_DOMAIN_EVENT_STOPPED:
            transition = virtevent.EVENT_LIFECYCLE_STOPPED
        elif event == libvirt.VIR_DOMAIN_EVENT_STARTED:
            transition = virtevent.EVENT_LIFECYCLE_STARTED
        elif event == libvirt.VIR_DOMAIN_EVENT_SUSPENDED:
            transition = virtevent.EVENT_LIFECYCLE_PAUSED
        elif event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
            transition = virtevent.EVENT_LIFECYCLE_RESUMED

        if transition is not None:
            self._queue_event(virtevent.LifecycleEvent(uuid, transition))

    def _queue_event(self, event):
        """Puts an event on the queue for dispatch.

        This method is called by the native event thread to
        put events on the queue for later dispatch by the
        green thread.
        """

        if self._event_queue is None:
            LOG.debug("Event loop thread is not active, "
                      "discarding event %s" % event)
            return

        # Queue the event...
        self._event_queue.put(event)

        # ...then wakeup the green thread to dispatch it
        c = ' '.encode()
        self._event_notify_send.write(c)
        self._event_notify_send.flush()

    def _dispatch_events(self):
        """Wait for & dispatch events from native thread

        Blocks until native thread indicates some events
        are ready. Then dispatches all queued events.
        """

        # Wait to be notified that there are some
        # events pending
        try:
            _c = self._event_notify_recv.read(1)
            assert _c
        except ValueError:
            return  # will be raised when pipe is closed

        # Process as many events as possible without
        # blocking
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get(block=False)
                self.emit_event(event)
            except native_Queue.Empty:
                pass

    def _init_events_pipe(self):
        """Create a self-pipe for the native thread to synchronize on.

        This code is taken from the eventlet tpool module, under terms
        of the Apache License v2.0.
        """

        self._event_queue = native_Queue.Queue()
        try:
            rpipe, wpipe = os.pipe()
            self._event_notify_send = greenio.GreenPipe(wpipe, 'wb', 0)
            self._event_notify_recv = greenio.GreenPipe(rpipe, 'rb', 0)
        except (ImportError, NotImplementedError):
            # This is Windows compatibility -- use a socket instead
            #  of a pipe because pipes don't really exist on Windows.
            sock = eventlet_util.__original_socket__(socket.AF_INET,
                                                     socket.SOCK_STREAM)
            sock.bind(('localhost', 0))
            sock.listen(50)
            csock = eventlet_util.__original_socket__(socket.AF_INET,
                                                      socket.SOCK_STREAM)
            csock.connect(('localhost', sock.getsockname()[1]))
            nsock, addr = sock.accept()
            self._event_notify_send = nsock.makefile('wb', 0)
            gsock = greenio.GreenSocket(csock)
            self._event_notify_recv = gsock.makefile('rb', 0)

    def _init_events(self):
        """Initializes the libvirt events subsystem.

        This requires running a native thread to provide the
        libvirt event loop integration. This forwards events
        to a green thread which does the actual dispatching.
        """

        self._init_events_pipe()

        LOG.debug("Starting native event thread")
        event_thread = native_threading.Thread(target=self._native_thread)
        event_thread.setDaemon(True)
        event_thread.start()

        LOG.debug("Starting green dispatch thread")
        dispatch_thread = eventlet.spawn(self._dispatch_thread)

    def init_host(self, host):
        libvirt.registerErrorHandler(libvirt_error_handler, None)
        libvirt.virEventRegisterDefaultImpl()

        if not self.has_min_version(MIN_LIBVIRT_VERSION):
            major = MIN_LIBVIRT_VERSION[0]
            minor = MIN_LIBVIRT_VERSION[1]
            micro = MIN_LIBVIRT_VERSION[2]
            LOG.error(_('Nova requires libvirt version '
                        '%(major)i.%(minor)i.%(micro)i or greater.') %
                        locals())

        self._init_events()

    def _get_connection(self):
        with self._wrapped_conn_lock:
            wrapped_conn = self._wrapped_conn

        if not wrapped_conn or not self._test_connection(wrapped_conn):
            LOG.debug(_('Connecting to libvirt: %s'), self.uri())
            if not CONF.libvirt_nonblocking:
                wrapped_conn = self._connect(self.uri(), self.read_only)
            else:
                wrapped_conn = tpool.proxy_call(
                    (libvirt.virDomain, libvirt.virConnect),
                    self._connect, self.uri(), self.read_only)
            with self._wrapped_conn_lock:
                self._wrapped_conn = wrapped_conn

            try:
                LOG.debug("Registering for lifecycle events %s" % str(self))
                wrapped_conn.domainEventRegisterAny(
                    None,
                    libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                    self._event_lifecycle_callback,
                    self)
            except Exception as e:
                LOG.warn(_("URI %s does not support events"),
                         self.uri())

            if self.has_min_version(MIN_LIBVIRT_CLOSE_CALLBACK_VERSION):
                try:
                    LOG.debug("Registering for connection events: %s" %
                              str(self))
                    wrapped_conn.registerCloseCallback(
                        self._close_callback, None)
                except libvirt.libvirtError:
                    LOG.debug(_("URI %s does not support connection events"),
                             self.uri())

        return wrapped_conn

    _conn = property(_get_connection)

    def _close_callback(self, conn, reason, opaque):
        with self._wrapped_conn_lock:
            if conn == self._wrapped_conn:
                LOG.info(_("Connection to libvirt lost: %s") % reason)
                self._wrapped_conn = None

    @staticmethod
    def _test_connection(conn):
        try:
            conn.getLibVersion()
            return True
        except libvirt.libvirtError as e:
            if (e.get_error_code() in (libvirt.VIR_ERR_SYSTEM_ERROR,
                                       libvirt.VIR_ERR_INTERNAL_ERROR) and
                e.get_error_domain() in (libvirt.VIR_FROM_REMOTE,
                                         libvirt.VIR_FROM_RPC)):
                LOG.debug(_('Connection to libvirt broke'))
                return False
            raise

    @staticmethod
    def uri():
        if CONF.libvirt_type == 'uml':
            uri = CONF.libvirt_uri or 'uml:///system'
        elif CONF.libvirt_type == 'xen':
            uri = CONF.libvirt_uri or 'xen:///'
        elif CONF.libvirt_type == 'lxc':
            uri = CONF.libvirt_uri or 'lxc:///'
        else:
            uri = CONF.libvirt_uri or 'qemu:///system'
        return uri

    @staticmethod
    def _connect(uri, read_only):
        def _connect_auth_cb(creds, opaque):
            if len(creds) == 0:
                return 0
            LOG.warning(
                _("Can not handle authentication request for %d credentials")
                % len(creds))
            raise exception.NovaException(
                _("Can not handle authentication request for %d credentials")
                % len(creds))

        auth = [[libvirt.VIR_CRED_AUTHNAME,
                 libvirt.VIR_CRED_ECHOPROMPT,
                 libvirt.VIR_CRED_REALM,
                 libvirt.VIR_CRED_PASSPHRASE,
                 libvirt.VIR_CRED_NOECHOPROMPT,
                 libvirt.VIR_CRED_EXTERNAL],
                _connect_auth_cb,
                None]

        try:
            if read_only:
                return libvirt.openReadOnly(uri)
            else:
                return libvirt.openAuth(uri, auth, 0)
        except libvirt.libvirtError as ex:
            LOG.exception(_("Connection to libvirt failed: %s"), ex)
            payload = dict(ip=LibvirtDriver.get_host_ip_addr(),
                           method='_connect',
                           reason=ex)
            notifier.notify(nova_context.get_admin_context(),
                            notifier.publisher_id('compute'),
                            'compute.libvirt.error',
                            notifier.ERROR,
                            payload)
            pass

    def get_num_instances(self):
        """Efficient override of base instance_exists method."""
        return self._conn.numOfDomains()

    def instance_exists(self, instance_name):
        """Efficient override of base instance_exists method."""
        try:
            self._lookup_by_name(instance_name)
            return True
        except exception.NovaException:
            return False

    def legacy_nwinfo(self):
        return True

    # TODO(Shrews): Remove when libvirt Bugzilla bug # 836647 is fixed.
    def list_instance_ids(self):
        if self._conn.numOfDomains() == 0:
            return []
        return self._conn.listDomainsID()

    def list_instances(self):
        names = []
        for domain_id in self.list_instance_ids():
            try:
                # We skip domains with ID 0 (hypervisors).
                if domain_id != 0:
                    domain = self._lookup_by_id(domain_id)
                    names.append(domain.name())
            except exception.InstanceNotFound:
                # Ignore deleted instance while listing
                continue

        # extend instance list to contain also defined domains
        names.extend([vm for vm in self._conn.listDefinedDomains()
                    if vm not in names])

        return names

    def list_instance_uuids(self):
        uuids = set()
        for domain_id in self.list_instance_ids():
            try:
                # We skip domains with ID 0 (hypervisors).
                if domain_id != 0:
                    domain = self._lookup_by_id(domain_id)
                    uuids.add(domain.UUIDString())
            except exception.InstanceNotFound:
                # Ignore deleted instance while listing
                continue

        # extend instance list to contain also defined domains
        for domain_name in self._conn.listDefinedDomains():
            try:
                uuids.add(self._lookup_by_name(domain_name).UUIDString())
            except exception.InstanceNotFound:
                # Ignore deleted instance while listing
                continue

        return list(uuids)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        for (network, mapping) in network_info:
            self.vif_driver.plug(instance, (network, mapping))

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        for (network, mapping) in network_info:
            self.vif_driver.unplug(instance, (network, mapping))

    def _destroy(self, instance):
        try:
            virt_dom = self._lookup_by_name(instance['name'])
        except exception.NotFound:
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
                if errcode == libvirt.VIR_ERR_OPERATION_INVALID:
                    # If the instance is already shut off, we get this:
                    # Code=55 Error=Requested operation is not valid:
                    # domain is not running
                    (state, _max_mem, _mem, _cpus, _t) = virt_dom.info()
                    state = LIBVIRT_POWER_STATE[state]
                    if state == power_state.SHUTDOWN:
                        is_okay = True

                if not is_okay:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_("Error from libvirt during destroy. "
                                      "Code=%(errcode)s Error=%(e)s") %
                                    locals(), instance=instance)

        def _wait_for_destroy(expected_domid):
            """Called at an interval until the VM is gone."""
            # NOTE(vish): If the instance disappears during the destroy
            #             we ignore it so the cleanup can still be
            #             attempted because we would prefer destroy to
            #             never fail.
            try:
                dom_info = self.get_info(instance)
                state = dom_info['state']
                new_domid = dom_info['id']
            except exception.NotFound:
                LOG.error(_("During wait destroy, instance disappeared."),
                          instance=instance)
                raise loopingcall.LoopingCallDone()

            if state == power_state.SHUTDOWN:
                LOG.info(_("Instance destroyed successfully."),
                         instance=instance)
                raise loopingcall.LoopingCallDone()

            # NOTE(wangpan): If the instance was booted again after destroy,
            #                this may be a endless loop, so check the id of
            #                domain here, if it changed and the instance is
            #                still running, we should destroy it again.
            # see https://bugs.launchpad.net/nova/+bug/1111213 for more details
            if new_domid != expected_domid:
                LOG.info(_("Instance may be started again."),
                         instance=instance)
                kwargs['is_running'] = True
                raise loopingcall.LoopingCallDone()

        kwargs = {'is_running': False}
        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_destroy,
                                                     old_domid)
        timer.start(interval=0.5).wait()
        if kwargs['is_running']:
            LOG.info(_("Going to destroy instance again."), instance=instance)
            self._destroy(instance)

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True):
        self._destroy(instance)
        self._cleanup(instance, network_info, block_device_info, destroy_disks)

    def _undefine_domain(self, instance):
        try:
            virt_dom = self._lookup_by_name(instance['name'])
        except exception.NotFound:
            virt_dom = None
        if virt_dom:
            try:
                try:
                    virt_dom.undefineFlags(
                        libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
                except libvirt.libvirtError:
                    LOG.debug(_("Error from libvirt during undefineFlags."
                        " Retrying with undefine"), instance=instance)
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
                    LOG.error(_("Error from libvirt during undefine. "
                                  "Code=%(errcode)s Error=%(e)s") %
                                locals(), instance=instance)

    def _cleanup(self, instance, network_info, block_device_info,
                 destroy_disks):
        self._undefine_domain(instance)
        self.unplug_vifs(instance, network_info)
        retry = True
        while retry:
            try:
                self.firewall_driver.unfilter_instance(instance,
                                                    network_info=network_info)
            except libvirt.libvirtError as e:
                try:
                    state = self.get_info(instance)['state']
                except exception.NotFound:
                    state = power_state.SHUTDOWN

                if state != power_state.SHUTDOWN:
                    LOG.warn(_("Instance may be still running, destroy "
                               "it again."), instance=instance)
                    self._destroy(instance)
                else:
                    retry = False
                    errcode = e.get_error_code()
                    LOG.error(_("Error from libvirt during unfilter. "
                                  "Code=%(errcode)s Error=%(e)s") %
                                locals(), instance=instance)
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
            disk_dev = vol['mount_device'].rpartition("/")[2]
            self.volume_driver_method('disconnect_volume',
                                      connection_info,
                                      disk_dev)

        if destroy_disks:
            target = libvirt_utils.get_instance_path(instance)
            LOG.info(_('Deleting instance files %(target)s') % locals(),
                     instance=instance)
            if os.path.exists(target):
                # If we fail to get rid of the directory
                # tree, this shouldn't block deletion of
                # the instance as whole.
                try:
                    shutil.rmtree(target)
                except OSError as e:
                    LOG.error(_("Failed to cleanup directory %(target)s: %(e)s"
                                ) % locals())

            #NOTE(bfilippov): destroy all LVM disks for this instance
            self._cleanup_lvm(instance)

    def _cleanup_lvm(self, instance):
        """Delete all LVM disks for given instance object."""
        disks = self._lvm_disks(instance)
        if disks:
            libvirt_utils.remove_logical_volumes(*disks)

    def _lvm_disks(self, instance):
        """Returns all LVM disks for given instance object."""
        if CONF.libvirt_images_volume_group:
            vg = os.path.join('/dev', CONF.libvirt_images_volume_group)
            if not os.path.exists(vg):
                return []
            pattern = '%s_' % instance['name']

            def belongs_to_instance(disk):
                return disk.startswith(pattern)

            def fullpath(name):
                return os.path.join(vg, name)

            logical_volumes = libvirt_utils.list_logical_volumes(vg)

            disk_names = filter(belongs_to_instance, logical_volumes)
            disks = map(fullpath, disk_names)
            return disks
        return []

    def get_volume_connector(self, instance):
        if not self._initiator:
            self._initiator = libvirt_utils.get_iscsi_initiator()
            if not self._initiator:
                LOG.debug(_('Could not determine iscsi initiator name'),
                          instance=instance)

        if not self._fc_wwnns:
            self._fc_wwnns = libvirt_utils.get_fc_wwnns()
            if not self._fc_wwnns or len(self._fc_wwnns) == 0:
                LOG.debug(_('Could not determine fibre channel '
                               'world wide node names'),
                          instance=instance)

        if not self._fc_wwpns:
            self._fc_wwpns = libvirt_utils.get_fc_wwpns()
            if not self._fc_wwpns or len(self._fc_wwpns) == 0:
                LOG.debug(_('Could not determine fibre channel '
                               'world wide port names'),
                          instance=instance)

        connector = {'ip': CONF.my_ip,
                     'host': CONF.host}

        if self._initiator:
            connector['initiator'] = self._initiator

        if self._fc_wwnns and self._fc_wwpns:
            connector["wwnns"] = self._fc_wwnns
            connector["wwpns"] = self._fc_wwpns

        return connector

    def _cleanup_resize(self, instance, network_info):
        target = libvirt_utils.get_instance_path(instance) + "_resize"
        if os.path.exists(target):
            shutil.rmtree(target)

        if instance['host'] != CONF.host:
            self._undefine_domain(instance)
            self.unplug_vifs(instance, network_info)
            self.firewall_driver.unfilter_instance(instance, network_info)

    def volume_driver_method(self, method_name, connection_info,
                             *args, **kwargs):
        driver_type = connection_info.get('driver_volume_type')
        if driver_type not in self.volume_drivers:
            raise exception.VolumeDriverNotFound(driver_type=driver_type)
        driver = self.volume_drivers[driver_type]
        method = getattr(driver, method_name)
        return method(connection_info, *args, **kwargs)

    def attach_volume(self, connection_info, instance, mountpoint):
        instance_name = instance['name']
        virt_dom = self._lookup_by_name(instance_name)
        disk_dev = mountpoint.rpartition("/")[2]
        disk_info = {
            'dev': disk_dev,
            'bus': blockinfo.get_disk_bus_for_disk_dev(CONF.libvirt_type,
                                                       disk_dev),
            'type': 'disk',
            }
        conf = self.volume_driver_method('connect_volume',
                                         connection_info,
                                         disk_info)
        self.set_cache_mode(conf)

        try:
            # NOTE(vish): We can always affect config because our
            #             domains are persistent, but we should only
            #             affect live if the domain is running.
            flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
            state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
            if state == power_state.RUNNING:
                flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
            virt_dom.attachDeviceFlags(conf.to_xml(), flags)
        except Exception as ex:
            if isinstance(ex, libvirt.libvirtError):
                errcode = ex.get_error_code()
                if errcode == libvirt.VIR_ERR_OPERATION_FAILED:
                    self.volume_driver_method('disconnect_volume',
                                              connection_info,
                                              disk_dev)
                    raise exception.DeviceIsBusy(device=disk_dev)

            with excutils.save_and_reraise_exception():
                self.volume_driver_method('disconnect_volume',
                                          connection_info,
                                          disk_dev)

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
            virt_dom = self._lookup_by_name(instance['name'])
            xml = virt_dom.XMLDesc(0)
        except exception.InstanceNotFound:
            disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                                instance,
                                                block_device_info)
            xml = self.to_xml(instance, network_info, disk_info,
                              block_device_info=block_device_info)
        return xml

    def detach_volume(self, connection_info, instance, mountpoint):
        instance_name = instance['name']
        disk_dev = mountpoint.rpartition("/")[2]
        try:
            virt_dom = self._lookup_by_name(instance_name)
            xml = self._get_disk_xml(virt_dom.XMLDesc(0), disk_dev)
            if not xml:
                raise exception.DiskNotFound(location=disk_dev)
            else:
                # NOTE(vish): We can always affect config because our
                #             domains are persistent, but we should only
                #             affect live if the domain is running.
                flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
                state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
                if state == power_state.RUNNING:
                    flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
                virt_dom.detachDeviceFlags(xml, flags)
        except libvirt.libvirtError as ex:
            # NOTE(vish): This is called to cleanup volumes after live
            #             migration, so we should still disconnect even if
            #             the instance doesn't exist here anymore.
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                # NOTE(vish):
                LOG.warn(_("During detach_volume, instance disappeared."))
            else:
                raise

        self.volume_driver_method('disconnect_volume',
                                  connection_info,
                                  disk_dev)

    @exception.wrap_exception()
    def attach_interface(self, instance, image_meta, network_info):
        virt_dom = self._lookup_by_name(instance['name'])
        for (network, mapping) in network_info:
            self.vif_driver.plug(instance, (network, mapping))
            self.firewall_driver.setup_basic_filtering(instance,
                                                       [(network, mapping)])
            cfg = self.vif_driver.get_config(instance, network, mapping,
                                             image_meta)
            try:
                flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
                state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
                if state == power_state.RUNNING:
                    flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
                virt_dom.attachDeviceFlags(cfg.to_xml(), flags)
            except libvirt.libvirtError as ex:
                LOG.error(_('attaching network adapter failed.'),
                         instance=instance)
                self.vif_driver.unplug(instance, (network, mapping))
                raise exception.InterfaceAttachFailed(instance)

    @exception.wrap_exception()
    def detach_interface(self, instance, network_info):
        virt_dom = self._lookup_by_name(instance['name'])
        for (network, mapping) in network_info:
            cfg = self.vif_driver.get_config(instance, network, mapping, None)
            try:
                self.vif_driver.unplug(instance, (network, mapping))
                flags = libvirt.VIR_DOMAIN_AFFECT_CONFIG
                state = LIBVIRT_POWER_STATE[virt_dom.info()[0]]
                if state == power_state.RUNNING:
                    flags |= libvirt.VIR_DOMAIN_AFFECT_LIVE
                virt_dom.detachDeviceFlags(cfg.to_xml(), flags)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                    LOG.warn(_("During detach_interface, "
                               "instance disappeared."),
                             instance=instance)
                else:
                    LOG.error(_('detaching network adapter failed.'),
                             instance=instance)
                    raise exception.InterfaceDetachFailed(instance)

    def snapshot(self, context, instance, image_href, update_task_state):
        """Create snapshot from a running VM instance.

        This command only works with qemu 0.14+
        """
        try:
            virt_dom = self._lookup_by_name(instance['name'])
        except exception.InstanceNotFound:
            raise exception.InstanceNotRunning(instance_id=instance['uuid'])

        (image_service, image_id) = glance.get_remote_image_service(
            context, instance['image_ref'])
        try:
            base = image_service.show(context, image_id)
        except exception.ImageNotFound:
            base = {}

        _image_service = glance.get_remote_image_service(context, image_href)
        snapshot_image_service, snapshot_image_id = _image_service
        snapshot = snapshot_image_service.show(context, snapshot_image_id)

        metadata = {'is_public': False,
                    'status': 'active',
                    'name': snapshot['name'],
                    'properties': {
                                   'kernel_id': instance['kernel_id'],
                                   'image_location': 'snapshot',
                                   'image_state': 'available',
                                   'owner_id': instance['project_id'],
                                   'ramdisk_id': instance['ramdisk_id'],
                                   }
                    }

        disk_path = libvirt_utils.find_disk(virt_dom)
        source_format = libvirt_utils.get_disk_type(disk_path)

        image_format = CONF.snapshot_image_format or source_format

        # NOTE(bfilippov): save lvm as raw
        if image_format == 'lvm':
            image_format = 'raw'

        # NOTE(vish): glance forces ami disk format to be ami
        if base.get('disk_format') == 'ami':
            metadata['disk_format'] = 'ami'
        else:
            metadata['disk_format'] = image_format

        metadata['container_format'] = base.get('container_format', 'bare')

        snapshot_name = uuid.uuid4().hex

        (state, _max_mem, _mem, _cpus, _t) = virt_dom.info()
        state = LIBVIRT_POWER_STATE[state]

        # NOTE(rmk): Live snapshots require QEMU 1.3 and Libvirt 1.0.0.
        #            These restrictions can be relaxed as other configurations
        #            can be validated.
        if self.has_min_version(MIN_LIBVIRT_LIVESNAPSHOT_VERSION,
                                MIN_QEMU_LIVESNAPSHOT_VERSION,
                                REQ_HYPERVISOR_LIVESNAPSHOT) \
                and not source_format == "lvm":
            live_snapshot = True
        else:
            live_snapshot = False

        # NOTE(rmk): We cannot perform live snapshots when a managedSave
        #            file is present, so we will use the cold/legacy method
        #            for instances which are shutdown.
        if state == power_state.SHUTDOWN:
            live_snapshot = False

        # NOTE(dkang): managedSave does not work for LXC
        if CONF.libvirt_type != 'lxc' and not live_snapshot:
            if state == power_state.RUNNING or state == power_state.PAUSED:
                virt_dom.managedSave(0)

        snapshot_backend = self.image_backend.snapshot(disk_path,
                snapshot_name,
                image_type=source_format)

        if live_snapshot:
            LOG.info(_("Beginning live snapshot process"),
                     instance=instance)
        else:
            LOG.info(_("Beginning cold snapshot process"),
                     instance=instance)
            snapshot_backend.snapshot_create()

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)
        snapshot_directory = CONF.libvirt_snapshots_directory
        fileutils.ensure_tree(snapshot_directory)
        with utils.tempdir(dir=snapshot_directory) as tmpdir:
            try:
                out_path = os.path.join(tmpdir, snapshot_name)
                if live_snapshot:
                    # NOTE (rmk): libvirt needs to be able to write to the
                    #             temp directory, which is owned nova.
                    utils.execute('chmod', '777', tmpdir, run_as_root=True)
                    self._live_snapshot(virt_dom, disk_path, out_path,
                                        image_format)
                else:
                    snapshot_backend.snapshot_extract(out_path, image_format)
            finally:
                if not live_snapshot:
                    snapshot_backend.snapshot_delete()
                # NOTE(dkang): because previous managedSave is not called
                #              for LXC, _create_domain must not be called.
                if CONF.libvirt_type != 'lxc' and not live_snapshot:
                    if state == power_state.RUNNING:
                        self._create_domain(domain=virt_dom)
                    elif state == power_state.PAUSED:
                        self._create_domain(domain=virt_dom,
                                launch_flags=libvirt.VIR_DOMAIN_START_PAUSED)
                LOG.info(_("Snapshot extracted, beginning image upload"),
                         instance=instance)

            # Upload that image to the image service

            update_task_state(task_state=task_states.IMAGE_UPLOADING,
                     expected_state=task_states.IMAGE_PENDING_UPLOAD)
            with libvirt_utils.file_open(out_path) as image_file:
                image_service.update(context,
                                     image_href,
                                     metadata,
                                     image_file)
                LOG.info(_("Snapshot image upload complete"),
                         instance=instance)

    def _live_snapshot(self, domain, disk_path, out_path, image_format):
        """Snapshot an instance without downtime."""
        # Save a copy of the domain's running XML file
        xml = domain.XMLDesc(0)

        # Abort is an idempotent operation, so make sure any block
        # jobs which may have failed are ended.
        try:
            domain.blockJobAbort(disk_path, 0)
        except Exception:
            pass

        def _wait_for_block_job(domain, disk_path):
            status = domain.blockJobInfo(disk_path, 0)
            try:
                cur = status.get('cur', 0)
                end = status.get('end', 0)
            except Exception:
                return False

            if cur == end and cur != 0 and end != 0:
                return False
            else:
                return True

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

            while _wait_for_block_job(domain, disk_path):
                time.sleep(0.5)

            domain.blockJobAbort(disk_path, 0)
            libvirt_utils.chown(disk_delta, os.getuid())
        finally:
            self._conn.defineXML(xml)

        # Convert the delta (CoW) image with a backing file to a flat
        # image with no backing file.
        libvirt_utils.extract_snapshot(disk_delta, 'qcow2', None,
                                       out_path, image_format)

    def reboot(self, context, instance, network_info, reboot_type='SOFT',
               block_device_info=None, bad_volumes_callback=None):
        """Reboot a virtual machine, given an instance reference."""
        if reboot_type == 'SOFT':
            # NOTE(vish): This will attempt to do a graceful shutdown/restart.
            if self._soft_reboot(instance):
                LOG.info(_("Instance soft rebooted successfully."),
                         instance=instance)
                return
            else:
                LOG.warn(_("Failed to soft reboot instance."),
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
        dom = self._lookup_by_name(instance["name"])
        (state, _max_mem, _mem, _cpus, _t) = dom.info()
        state = LIBVIRT_POWER_STATE[state]
        old_domid = dom.ID()
        # NOTE(vish): This check allows us to reboot an instance that
        #             is already shutdown.
        if state == power_state.RUNNING:
            dom.shutdown()
        # NOTE(vish): This actually could take slighty longer than the
        #             FLAG defines depending on how long the get_info
        #             call takes to return.
        for x in xrange(CONF.libvirt_wait_soft_reboot_seconds):
            dom = self._lookup_by_name(instance["name"])
            (state, _max_mem, _mem, _cpus, _t) = dom.info()
            state = LIBVIRT_POWER_STATE[state]
            new_domid = dom.ID()

            # NOTE(ivoks): By checking domain IDs, we make sure we are
            #              not recreating domain that's already running.
            if old_domid != new_domid:
                if state in [power_state.SHUTDOWN,
                             power_state.CRASHED]:
                    LOG.info(_("Instance shutdown successfully."),
                             instance=instance)
                    self._create_domain(domain=dom)
                    timer = loopingcall.FixedIntervalLoopingCall(
                        self._wait_for_running, instance)
                    timer.start(interval=0.5).wait()
                    return True
                else:
                    LOG.info(_("Instance may have been rebooted during soft "
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
        disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                            instance,
                                            block_device_info)
        # NOTE(vish): This could generate the wrong device_format if we are
        #             using the raw backend and the images don't exist yet.
        #             The create_images_and_backing below doesn't properly
        #             regenerate raw backend images, however, so when it
        #             does we need to (re)generate the xml after the images
        #             are in place.
        xml = self.to_xml(instance, network_info, disk_info,
                          block_device_info=block_device_info,
                          write_to_disk=True)

        # NOTE (rmk): Re-populate any missing backing files.
        disk_info_json = self.get_instance_disk_info(instance['name'], xml)
        self._create_images_and_backing(context, instance, disk_info_json)

        # Initialize all the necessary networking, block devices and
        # start the instance.
        self._create_domain_and_network(xml, instance, network_info,
                                        block_device_info)

        def _wait_for_reboot():
            """Called at an interval until the VM is running again."""
            state = self.get_info(instance)['state']

            if state == power_state.RUNNING:
                LOG.info(_("Instance rebooted successfully."),
                         instance=instance)
                raise loopingcall.LoopingCallDone()

        timer = loopingcall.FixedIntervalLoopingCall(_wait_for_reboot)
        timer.start(interval=0.5).wait()

    def pause(self, instance):
        """Pause VM instance."""
        dom = self._lookup_by_name(instance['name'])
        dom.suspend()

    def unpause(self, instance):
        """Unpause paused VM instance."""
        dom = self._lookup_by_name(instance['name'])
        dom.resume()

    def power_off(self, instance):
        """Power off the specified instance."""
        self._destroy(instance)

    def power_on(self, instance):
        """Power on the specified instance."""
        dom = self._lookup_by_name(instance['name'])
        self._create_domain(domain=dom, instance=instance)
        timer = loopingcall.FixedIntervalLoopingCall(self._wait_for_running,
                                                     instance)
        timer.start(interval=0.5).wait()

    def suspend(self, instance):
        """Suspend the specified instance."""
        dom = self._lookup_by_name(instance['name'])
        dom.managedSave(0)

    def resume(self, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        xml = self._get_existing_domain_xml(instance, network_info,
                                            block_device_info)
        self._create_domain_and_network(xml, instance, network_info,
                                        block_device_info)

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """resume guest state when a host is booted."""
        # Check if the instance is running already and avoid doing
        # anything if it is.
        if self.instance_exists(instance['name']):
            domain = self._lookup_by_name(instance['name'])
            state = LIBVIRT_POWER_STATE[domain.info()[0]]

            ignored_states = (power_state.RUNNING,
                              power_state.SUSPENDED,
                              power_state.NOSTATE,
                              power_state.PAUSED)

            if state in ignored_states:
                return

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

        rescue_images = {
            'image_id': CONF.rescue_image_id or instance['image_ref'],
            'kernel_id': CONF.rescue_kernel_id or instance['kernel_id'],
            'ramdisk_id': CONF.rescue_ramdisk_id or instance['ramdisk_id'],
        }
        disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                            instance,
                                            None,
                                            image_meta,
                                            rescue=True)
        self._create_image(context, instance,
                           disk_info['mapping'],
                           '.rescue', rescue_images,
                           network_info=network_info,
                           admin_pass=rescue_password)
        xml = self.to_xml(instance, network_info, disk_info,
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
        virt_dom = self._lookup_by_name(instance['name'])
        self._destroy(instance)
        self._create_domain(xml, virt_dom)
        libvirt_utils.file_delete(unrescue_xml_path)
        rescue_files = os.path.join(instance_dir, "*.rescue")
        for rescue_file in glob.iglob(rescue_files):
            libvirt_utils.file_delete(rescue_file)

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def _enable_hairpin(self, xml):
        interfaces = self.get_interfaces(xml)
        for interface in interfaces:
            utils.execute('tee',
                          '/sys/class/net/%s/brport/hairpin_mode' % interface,
                          process_input='1',
                          run_as_root=True,
                          check_exit_code=[0, 1])

    # NOTE(ilyaalekseyev): Implementation like in multinics
    # for xenapi(tr3buchet)
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        self._create_image(context, instance,
                           disk_info['mapping'],
                           network_info=network_info,
                           block_device_info=block_device_info,
                           files=injected_files,
                           admin_pass=admin_password)
        xml = self.to_xml(instance, network_info,
                          disk_info, image_meta,
                          block_device_info=block_device_info,
                          write_to_disk=True)

        self._create_domain_and_network(xml, instance, network_info,
                                        block_device_info)
        LOG.debug(_("Instance is running"), instance=instance)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            state = self.get_info(instance)['state']

            if state == power_state.RUNNING:
                LOG.info(_("Instance spawned successfully."),
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
        LOG.info(_('data: %(data)r, fpath: %(fpath)r') % locals())
        fp = open(fpath, 'a+')
        fp.write(data)
        return fpath

    def get_console_output(self, instance):
        virt_dom = self._lookup_by_name(instance['name'])
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
                libvirt_utils.chown(path, os.getuid())

                with libvirt_utils.file_open(path, 'rb') as fp:
                    log_data, remaining = utils.last_bytes(fp,
                                                           MAX_CONSOLE_BYTES)
                    if remaining > 0:
                        LOG.info(_('Truncated console log returned, %d bytes '
                                   'ignored'), remaining, instance=instance)
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
                LOG.info(_('Truncated console log returned, %d bytes ignored'),
                         remaining, instance=instance)
            return log_data

    @staticmethod
    def get_host_ip_addr():
        return CONF.my_ip

    def get_vnc_console(self, instance):
        def get_vnc_port_for_instance(instance_name):
            virt_dom = self._lookup_by_name(instance_name)
            xml = virt_dom.XMLDesc(0)
            # TODO(sleepsonthefloor): use etree instead of minidom
            dom = minidom.parseString(xml)

            for graphic in dom.getElementsByTagName('graphics'):
                if graphic.getAttribute('type') == 'vnc':
                    return graphic.getAttribute('port')

        port = get_vnc_port_for_instance(instance['name'])
        host = CONF.vncserver_proxyclient_address

        return {'host': host, 'port': port, 'internal_access_path': None}

    @exception.wrap_exception()
    def get_spice_console(self, instance):
        def get_spice_ports_for_instance(instance_name):
            virt_dom = self._lookup_by_name(instance_name)
            xml = virt_dom.XMLDesc(0)
            # TODO(sleepsonthefloor): use etree instead of minidom
            dom = minidom.parseString(xml)

            for graphic in dom.getElementsByTagName('graphics'):
                if graphic.getAttribute('type') == 'spice':
                    return (graphic.getAttribute('port'),
                            graphic.getAttribute('tlsPort'))

            return (None, None)

        ports = get_spice_ports_for_instance(instance['name'])
        host = CONF.spice.server_proxyclient_address

        return {'host': host, 'port': ports[0],
                'tlsPort': ports[1], 'internal_access_path': None}

    @staticmethod
    def _supports_direct_io(dirpath):

        if not hasattr(os, 'O_DIRECT'):
            LOG.debug("This python runtime does not support direct I/O")
            return False

        testfile = os.path.join(dirpath, ".directio.test")

        hasDirectIO = True
        try:
            f = os.open(testfile, os.O_CREAT | os.O_WRONLY | os.O_DIRECT)
            os.close(f)
            LOG.debug(_("Path '%(path)s' supports direct I/O") %
                      {'path': dirpath})
        except OSError as e:
            if e.errno == errno.EINVAL:
                LOG.debug(_("Path '%(path)s' does not support direct I/O: "
                            "'%(ex)s'") % {'path': dirpath, 'ex': str(e)})
                hasDirectIO = False
            else:
                with excutils.save_and_reraise_exception():
                    LOG.error(_("Error on '%(path)s' while checking "
                                "direct I/O: '%(ex)s'") %
                                {'path': dirpath, 'ex': str(e)})
        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Error on '%(path)s' while checking direct I/O: "
                            "'%(ex)s'") % {'path': dirpath, 'ex': str(e)})
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

        if not fs_format:
            fs_format = CONF.default_ephemeral_format

        if not CONF.libvirt_images_type == "lvm":
            libvirt_utils.create_image('raw', target,
                                       '%d%c' % (local_size, unit))
        if fs_format:
            utils.mkfs(fs_format, target, label)

    def _create_ephemeral(self, target, ephemeral_size, fs_label, os_type):
        self._create_local(target, ephemeral_size)
        disk.mkfs(os_type, fs_label, target)

    @staticmethod
    def _create_swap(target, swap_mb):
        """Create a swap file of specified size."""
        libvirt_utils.create_image('raw', target, '%dM' % swap_mb)
        utils.mkfs('swap', target)

    @staticmethod
    def _get_console_log_path(instance):
        return os.path.join(libvirt_utils.get_instance_path(instance),
                            'console.log')

    def _chown_console_log_for_instance(self, instance):
        console_log = self._get_console_log_path(instance)
        if os.path.exists(console_log):
            libvirt_utils.chown(console_log, os.getuid())

    def _create_image(self, context, instance,
                      disk_mapping, suffix='',
                      disk_images=None, network_info=None,
                      block_device_info=None, files=None, admin_pass=None):
        if not suffix:
            suffix = ''

        booted_from_volume = (
            (not bool(instance.get('image_ref')))
            or 'disk' not in disk_mapping
        )

        # syntactic nicety
        def basepath(fname='', suffix=suffix):
            return os.path.join(libvirt_utils.get_instance_path(instance),
                                fname + suffix)

        def image(fname, image_type=CONF.libvirt_images_type):
            return self.image_backend.image(instance,
                                            fname + suffix, image_type)

        def raw(fname):
            return image(fname, image_type='raw')

        # ensure directories exist and are writable
        fileutils.ensure_tree(basepath(suffix=''))

        LOG.info(_('Creating image'), instance=instance)

        # NOTE(dprince): for rescue console.log may already exist... chown it.
        self._chown_console_log_for_instance(instance)

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

        inst_type = flavors.extract_flavor(instance)

        # NOTE(ndipanov): Even if disk_mapping was passed in, which
        # currently happens only on rescue - we still don't want to
        # create a base image.
        if not booted_from_volume:
            root_fname = imagecache.get_cache_fname(disk_images, 'image_id')
            size = instance['root_gb'] * 1024 * 1024 * 1024

            if size == 0 or suffix == '.rescue':
                size = None

            image('disk').cache(fetch_func=libvirt_utils.fetch_image,
                                context=context,
                                filename=root_fname,
                                size=size,
                                image_id=disk_images['image_id'],
                                user_id=instance['user_id'],
                                project_id=instance['project_id'])

        # Lookup the filesystem type if required
        os_type_with_default = instance['os_type']
        if not os_type_with_default:
            os_type_with_default = 'default'

        ephemeral_gb = instance['ephemeral_gb']
        if 'disk.local' in disk_mapping:
            fn = functools.partial(self._create_ephemeral,
                                   fs_label='ephemeral0',
                                   os_type=instance["os_type"])
            fname = "ephemeral_%s_%s" % (ephemeral_gb, os_type_with_default)
            size = ephemeral_gb * 1024 * 1024 * 1024
            image('disk.local').cache(fetch_func=fn,
                                      filename=fname,
                                      size=size,
                                      ephemeral_size=ephemeral_gb)

        for eph in driver.block_device_info_get_ephemerals(block_device_info):
            fn = functools.partial(self._create_ephemeral,
                                   fs_label='ephemeral%d' % eph['num'],
                                   os_type=instance["os_type"])
            size = eph['size'] * 1024 * 1024 * 1024
            fname = "ephemeral_%s_%s" % (eph['size'], os_type_with_default)
            image(blockinfo.get_eph_disk(eph)).cache(
                fetch_func=fn,
                filename=fname,
                size=size,
                ephemeral_size=eph['size'])

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
                size = swap_mb * 1024 * 1024
                image('disk.swap').cache(fetch_func=self._create_swap,
                                         filename="swap_%s" % swap_mb,
                                         size=size,
                                         swap_mb=swap_mb)

        # Config drive
        if configdrive.required_by(instance):
            LOG.info(_('Using config drive'), instance=instance)
            extra_md = {}
            if admin_pass:
                extra_md['admin_pass'] = admin_pass

            inst_md = instance_metadata.InstanceMetadata(instance,
                content=files, extra_md=extra_md)
            with configdrive.ConfigDriveBuilder(instance_md=inst_md) as cdb:
                configdrive_path = basepath(fname='disk.config')
                LOG.info(_('Creating config drive at %(path)s'),
                         {'path': configdrive_path}, instance=instance)

                try:
                    cdb.make_drive(configdrive_path)
                except processutils.ProcessExecutionError as e:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_('Creating config drive failed '
                                  'with error: %s'),
                                  e, instance=instance)

        # File injection
        elif CONF.libvirt_inject_partition != -2:
            target_partition = None
            if not instance['kernel_id']:
                target_partition = CONF.libvirt_inject_partition
                if target_partition == 0:
                    target_partition = None
            if CONF.libvirt_type == 'lxc':
                target_partition = None

            if CONF.libvirt_inject_key and instance['key_data']:
                key = str(instance['key_data'])
            else:
                key = None

            net = netutils.get_injected_network_template(network_info)

            metadata = instance.get('metadata')

            if not CONF.libvirt_inject_password:
                admin_pass = None

            if any((key, net, metadata, admin_pass, files)):
                # If we're not using config_drive, inject into root fs
                injection_path = image('disk').path
                img_id = instance['image_ref']

                for inj in ('key', 'net', 'metadata', 'admin_pass', 'files'):
                    if locals()[inj]:
                        LOG.info(_('Injecting %(inj)s into image '
                                   '%(img_id)s'), locals(), instance=instance)
                try:
                    disk.inject_data(injection_path,
                                     key, net, metadata, admin_pass, files,
                                     partition=target_partition,
                                     use_cow=CONF.use_cow_images,
                                     mandatory=('files',))
                except Exception as e:
                    with excutils.save_and_reraise_exception():
                        LOG.error(_('Error injecting data into image '
                                    '%(img_id)s (%(e)s)') % locals(),
                                  instance=instance)

        if CONF.libvirt_type == 'uml':
            libvirt_utils.chown(image('disk').path, 'root')

    def get_host_capabilities(self):
        """Returns an instance of config.LibvirtConfigCaps representing
           the capabilities of the host.
        """
        if not self._caps:
            xmlstr = self._conn.getCapabilities()
            self._caps = vconfig.LibvirtConfigCaps()
            self._caps.parse_str(xmlstr)
        return self._caps

    def get_host_uuid(self):
        """Returns a UUID representing the host."""
        caps = self.get_host_capabilities()
        return caps.host.uuid

    def get_host_cpu_for_guest(self):
        """Returns an instance of config.LibvirtConfigGuestCPU
           representing the host's CPU model & topology with
           policy for configuring a guest to match
        """

        caps = self.get_host_capabilities()
        hostcpu = caps.host.cpu
        guestcpu = vconfig.LibvirtConfigGuestCPU()

        guestcpu.model = hostcpu.model
        guestcpu.vendor = hostcpu.vendor
        guestcpu.arch = hostcpu.arch

        guestcpu.match = "exact"

        for hostfeat in hostcpu.features:
            guestfeat = vconfig.LibvirtConfigGuestCPUFeature(hostfeat.name)
            guestfeat.policy = "require"
            guestcpu.features.append(guestfeat)

        return guestcpu

    def get_guest_cpu_config(self):
        mode = CONF.libvirt_cpu_mode
        model = CONF.libvirt_cpu_model

        if mode is None:
            if CONF.libvirt_type == "kvm" or CONF.libvirt_type == "qemu":
                mode = "host-model"
            else:
                mode = "none"

        if mode == "none":
            return None

        if CONF.libvirt_type != "kvm" and CONF.libvirt_type != "qemu":
            msg = _("Config requested an explicit CPU model, but "
                    "the current libvirt hypervisor '%s' does not "
                    "support selecting CPU models") % CONF.libvirt_type
            raise exception.Invalid(msg)

        if mode == "custom" and model is None:
            msg = _("Config requested a custom CPU model, but no "
                    "model name was provided")
            raise exception.Invalid(msg)
        elif mode != "custom" and model is not None:
            msg = _("A CPU model name should not be set when a "
                    "host CPU model is requested")
            raise exception.Invalid(msg)

        LOG.debug(_("CPU mode '%(mode)s' model '%(model)s' was chosen")
                  % {'mode': mode, 'model': (model or "")})

        # TODO(berrange): in the future, when MIN_LIBVIRT_VERSION is
        # updated to be at least this new, we can kill off the elif
        # blocks here
        if self.has_min_version(MIN_LIBVIRT_HOST_CPU_VERSION):
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.mode = mode
            cpu.model = model
        elif mode == "custom":
            cpu = vconfig.LibvirtConfigGuestCPU()
            cpu.model = model
        elif mode == "host-model":
            cpu = self.get_host_cpu_for_guest()
        elif mode == "host-passthrough":
            msg = _("Passthrough of the host CPU was requested but "
                    "this libvirt version does not support this feature")
            raise exception.NovaException(msg)

        return cpu

    def get_guest_disk_config(self, instance, name, disk_mapping, inst_type,
                              image_type=None):
        image = self.image_backend.image(instance,
                                         name,
                                         image_type)
        disk_info = disk_mapping[name]
        return image.libvirt_info(disk_info['bus'],
                                  disk_info['dev'],
                                  disk_info['type'],
                                  self.disk_cachemode,
                                  inst_type['extra_specs'])

    def get_guest_storage_config(self, instance, image_meta,
                                 disk_info,
                                 rescue, block_device_info,
                                 inst_type):
        devices = []
        disk_mapping = disk_info['mapping']

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        if CONF.libvirt_type == "lxc":
            fs = vconfig.LibvirtConfigGuestFilesys()
            fs.source_type = "mount"
            fs.source_dir = os.path.join(
                libvirt_utils.get_instance_path(instance), 'rootfs')
            devices.append(fs)
        else:

            if rescue:
                diskrescue = self.get_guest_disk_config(instance,
                                                        'disk.rescue',
                                                        disk_mapping,
                                                        inst_type)
                devices.append(diskrescue)

                diskos = self.get_guest_disk_config(instance,
                                                    'disk',
                                                    disk_mapping,
                                                    inst_type)
                devices.append(diskos)
            else:
                if 'disk' in disk_mapping:
                    diskos = self.get_guest_disk_config(instance,
                                                        'disk',
                                                        disk_mapping,
                                                        inst_type)
                    devices.append(diskos)

                if 'disk.local' in disk_mapping:
                    disklocal = self.get_guest_disk_config(instance,
                                                           'disk.local',
                                                           disk_mapping,
                                                           inst_type)
                    devices.append(disklocal)
                    self.virtapi.instance_update(
                        nova_context.get_admin_context(), instance['uuid'],
                        {'default_ephemeral_device':
                             '/dev/' + disklocal.target_dev})

                for eph in driver.block_device_info_get_ephemerals(
                    block_device_info):
                    diskeph = self.get_guest_disk_config(
                        instance,
                        blockinfo.get_eph_disk(eph),
                        disk_mapping, inst_type)
                    devices.append(diskeph)

                if 'disk.swap' in disk_mapping:
                    diskswap = self.get_guest_disk_config(instance,
                                                          'disk.swap',
                                                          disk_mapping,
                                                          inst_type)
                    devices.append(diskswap)
                    self.virtapi.instance_update(
                        nova_context.get_admin_context(), instance['uuid'],
                        {'default_swap_device': '/dev/' + diskswap.target_dev})

                for vol in block_device_mapping:
                    connection_info = vol['connection_info']
                    info = disk_mapping[vol['mount_device']]
                    cfg = self.volume_driver_method('connect_volume',
                                                    connection_info,
                                                    info)
                    devices.append(cfg)

            if 'disk.config' in disk_mapping:
                diskconfig = self.get_guest_disk_config(instance,
                                                        'disk.config',
                                                        disk_mapping,
                                                        inst_type,
                                                        'raw')
                devices.append(diskconfig)

        for d in devices:
            self.set_cache_mode(d)

        return devices

    def get_guest_config_sysinfo(self, instance):
        sysinfo = vconfig.LibvirtConfigGuestSysinfo()

        sysinfo.system_manufacturer = version.vendor_string()
        sysinfo.system_product = version.product_string()
        sysinfo.system_version = version.version_string_with_package()

        sysinfo.system_serial = self.get_host_uuid()
        sysinfo.system_uuid = instance['uuid']

        return sysinfo

    def get_guest_config(self, instance, network_info, image_meta,
                         disk_info, rescue=None, block_device_info=None):
        """Get config data for parameters.

        :param rescue: optional dictionary that should contain the key
            'ramdisk_id' if a ramdisk is needed for the rescue image and
            'kernel_id' if a kernel is needed for the rescue image.
        """

        inst_type = self.virtapi.instance_type_get(
            nova_context.get_admin_context(read_deleted='yes'),
            instance['instance_type_id'])
        inst_path = libvirt_utils.get_instance_path(instance)
        disk_mapping = disk_info['mapping']

        CONSOLE = "console=tty0 console=ttyS0"

        guest = vconfig.LibvirtConfigGuest()
        guest.virt_type = CONF.libvirt_type
        guest.name = instance['name']
        guest.uuid = instance['uuid']
        guest.memory = inst_type['memory_mb'] * 1024
        guest.vcpus = inst_type['vcpus']
        guest.cpuset = CONF.vcpu_pin_set

        quota_items = ['cpu_shares', 'cpu_period', 'cpu_quota']
        for key, value in inst_type['extra_specs'].iteritems():
            scope = key.split(':')
            if len(scope) > 1 and scope[0] == 'quota':
                if scope[1] in quota_items:
                    setattr(guest, scope[1], value)

        guest.cpu = self.get_guest_cpu_config()

        if 'root' in disk_mapping and disk_mapping['root']['dev'] is not None:
            root_device_name = "/dev/" + disk_mapping['root']['dev']
        else:
            root_device_name = None

        if root_device_name:
            # NOTE(yamahata):
            # for nova.api.ec2.cloud.CloudController.get_metadata()
            self.virtapi.instance_update(
                nova_context.get_admin_context(), instance['uuid'],
                {'root_device_name': root_device_name})

        guest.os_type = vm_mode.get_from_instance(instance)

        if guest.os_type is None:
            if CONF.libvirt_type == "lxc":
                guest.os_type = vm_mode.EXE
            elif CONF.libvirt_type == "uml":
                guest.os_type = vm_mode.UML
            elif CONF.libvirt_type == "xen":
                guest.os_type = vm_mode.XEN
            else:
                guest.os_type = vm_mode.HVM

        if CONF.libvirt_type == "xen" and guest.os_type == vm_mode.HVM:
            guest.os_loader = CONF.xen_hvmloader_path

        if CONF.libvirt_type in ("kvm", "qemu"):
            caps = self.get_host_capabilities()
            if caps.host.cpu.arch in ("i686", "x86_64"):
                guest.sysinfo = self.get_guest_config_sysinfo(instance)
                guest.os_smbios = vconfig.LibvirtConfigGuestSMBIOS()

        if CONF.libvirt_type == "lxc":
            guest.os_type = vm_mode.EXE
            guest.os_init_path = "/sbin/init"
            guest.os_cmdline = CONSOLE
        elif CONF.libvirt_type == "uml":
            guest.os_type = vm_mode.UML
            guest.os_kernel = "/usr/bin/linux"
            guest.os_root = root_device_name
        else:
            if CONF.libvirt_type == "xen" and guest.os_type == vm_mode.XEN:
                guest.os_root = root_device_name
            else:
                guest.os_type = vm_mode.HVM

            if rescue:
                if rescue.get('kernel_id'):
                    guest.os_kernel = os.path.join(inst_path, "kernel.rescue")
                    if CONF.libvirt_type == "xen":
                        guest.os_cmdline = "ro"
                    else:
                        guest.os_cmdline = ("root=%s %s" % (root_device_name,
                                                            CONSOLE))

                if rescue.get('ramdisk_id'):
                    guest.os_initrd = os.path.join(inst_path, "ramdisk.rescue")
            elif instance['kernel_id']:
                guest.os_kernel = os.path.join(inst_path, "kernel")
                if CONF.libvirt_type == "xen":
                    guest.os_cmdline = "ro"
                else:
                    guest.os_cmdline = ("root=%s %s" % (root_device_name,
                                                        CONSOLE))
                if instance['ramdisk_id']:
                    guest.os_initrd = os.path.join(inst_path, "ramdisk")
            else:
                guest.os_boot_dev = "hd"

        if CONF.libvirt_type != "lxc" and CONF.libvirt_type != "uml":
            guest.acpi = True
            guest.apic = True

        clk = vconfig.LibvirtConfigGuestClock()
        clk.offset = "utc"
        guest.set_clock(clk)

        if CONF.libvirt_type == "kvm":
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

        for cfg in self.get_guest_storage_config(instance,
                                                 image_meta,
                                                 disk_info,
                                                 rescue,
                                                 block_device_info,
                                                 inst_type):
            guest.add_device(cfg)

        for (network, mapping) in network_info:
            cfg = self.vif_driver.get_config(instance,
                                             network, mapping,
                                             image_meta)
            guest.add_device(cfg)

        if CONF.libvirt_type == "qemu" or CONF.libvirt_type == "kvm":
            # The QEMU 'pty' driver throws away any data if no
            # client app is connected. Thus we can't get away
            # with a single type=pty console. Instead we have
            # to configure two separate consoles.
            consolelog = vconfig.LibvirtConfigGuestSerial()
            consolelog.type = "file"
            consolelog.source_path = self._get_console_log_path(instance)
            guest.add_device(consolelog)

            consolepty = vconfig.LibvirtConfigGuestSerial()
            consolepty.type = "pty"
            guest.add_device(consolepty)
        else:
            consolepty = vconfig.LibvirtConfigGuestConsole()
            consolepty.type = "pty"
            guest.add_device(consolepty)

        # We want a tablet if VNC is enabled,
        # or SPICE is enabled and the SPICE agent is disabled
        # NB: this implies that if both SPICE + VNC are enabled
        # at the same time, we'll get the tablet whether the
        # SPICE agent is used or not.
        need_usb_tablet = False
        if CONF.vnc_enabled:
            need_usb_tablet = CONF.use_usb_tablet
        elif CONF.spice.enabled and not CONF.spice.agent_enabled:
            need_usb_tablet = CONF.use_usb_tablet

        if need_usb_tablet and guest.os_type == vm_mode.HVM:
            tablet = vconfig.LibvirtConfigGuestInput()
            tablet.type = "tablet"
            tablet.bus = "usb"
            guest.add_device(tablet)

        if CONF.spice.enabled and CONF.spice.agent_enabled and \
                CONF.libvirt_type not in ('lxc', 'uml', 'xen'):
            channel = vconfig.LibvirtConfigGuestChannel()
            channel.target_name = "com.redhat.spice.0"
            guest.add_device(channel)

        # NB some versions of libvirt support both SPICE and VNC
        # at the same time. We're not trying to second guess which
        # those versions are. We'll just let libvirt report the
        # errors appropriately if the user enables both.

        if CONF.vnc_enabled and CONF.libvirt_type not in ('lxc', 'uml'):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "vnc"
            graphics.keymap = CONF.vnc_keymap
            graphics.listen = CONF.vncserver_listen
            guest.add_device(graphics)

        if CONF.spice.enabled and \
                CONF.libvirt_type not in ('lxc', 'uml', 'xen'):
            graphics = vconfig.LibvirtConfigGuestGraphics()
            graphics.type = "spice"
            graphics.keymap = CONF.spice.keymap
            graphics.listen = CONF.spice.server_listen
            guest.add_device(graphics)

        return guest

    def to_xml(self, instance, network_info, disk_info,
               image_meta=None, rescue=None,
               block_device_info=None, write_to_disk=False):
        LOG.debug(_("Start to_xml instance=%(instance)s "
                    "network_info=%(network_info)s "
                    "disk_info=%(disk_info)s "
                    "image_meta=%(image_meta)s rescue=%(rescue)s"
                    "block_device_info=%(block_device_info)s") %
                  locals())
        conf = self.get_guest_config(instance, network_info, image_meta,
                                     disk_info, rescue, block_device_info)
        xml = conf.to_xml()

        if write_to_disk:
            instance_dir = libvirt_utils.get_instance_path(instance)
            xml_path = os.path.join(instance_dir, 'libvirt.xml')
            libvirt_utils.write_to_file(xml_path, xml)

        LOG.debug(_('End to_xml instance=%(instance)s xml=%(xml)s') % locals())
        return xml

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

            msg = _("Error from libvirt while looking up %(instance_name)s: "
                    "[Error Code %(error_code)s] %(ex)s") % locals()
            raise exception.NovaException(msg)

    def get_info(self, instance):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        """
        virt_dom = self._lookup_by_name(instance['name'])
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': LIBVIRT_POWER_STATE[state],
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time,
                'id': virt_dom.ID()}

    def _create_domain(self, xml=None, domain=None,
                       instance=None, launch_flags=0, power_on=True):
        """Create a domain.

        Either domain or xml must be passed in. If both are passed, then
        the domain definition is overwritten from the xml.
        """
        inst_path = None
        if instance:
            inst_path = libvirt_utils.get_instance_path(instance)

        if CONF.libvirt_type == 'lxc':
            if not inst_path:
                inst_path = None

            container_dir = os.path.join(inst_path, 'rootfs')
            fileutils.ensure_tree(container_dir)
            image = self.image_backend.image(instance, 'disk')
            disk.setup_container(image.path,
                                 container_dir=container_dir,
                                 use_cow=CONF.use_cow_images)

        if xml:
            domain = self._conn.defineXML(xml)
        if power_on:
            domain.createWithFlags(launch_flags)
        self._enable_hairpin(domain.XMLDesc(0))

        # NOTE(uni): Now the container is running with its own private mount
        # namespace and so there is no need to keep the container rootfs
        # mounted in the host namespace
        if CONF.libvirt_type == 'lxc':
            state = self.get_info(instance)['state']
            container_dir = os.path.join(inst_path, 'rootfs')
            if state == power_state.RUNNING:
                disk.clean_lxc_namespace(container_dir=container_dir)
            else:
                disk.teardown_container(container_dir=container_dir)

        return domain

    def _create_domain_and_network(self, xml, instance, network_info,
                                   block_device_info=None, power_on=True):

        """Do required network setup and create domain."""
        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)

        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device'].rpartition("/")[2]
            disk_info = {
                'dev': disk_dev,
                'bus': blockinfo.get_disk_bus_for_disk_dev(CONF.libvirt_type,
                                                           disk_dev),
                'type': 'disk',
                }
            self.volume_driver_method('connect_volume',
                                      connection_info,
                                      disk_info)

        self.plug_vifs(instance, network_info)
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        domain = self._create_domain(xml, instance=instance, power_on=power_on)

        self.firewall_driver.apply_instance_filter(instance, network_info)
        return domain

    def get_all_block_devices(self):
        """
        Return all block devices in use on this node.
        """
        devices = []
        for dom_id in self.list_instance_ids():
            try:
                domain = self._lookup_by_id(dom_id)
                doc = etree.fromstring(domain.XMLDesc(0))
            except exception.InstanceNotFound:
                LOG.info(_("libvirt can't find a domain with id: %s") % dom_id)
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

    def get_disks(self, instance_name):
        """
        Note that this function takes an instance name.

        Returns a list of all block devices for this domain.
        """
        domain = self._lookup_by_name(instance_name)
        xml = domain.XMLDesc(0)

        try:
            doc = etree.fromstring(xml)
        except Exception:
            return []

        return filter(bool,
                      [target.get("dev")
                       for target in doc.findall('devices/disk/target')])

    def get_interfaces(self, xml):
        """
        Note that this function takes a domain xml.

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

    def _get_cpuset_ids(self):
        """
        Parsing vcpu_pin_set config.

        Returns a list of pcpu ids can be used by instances.
        """
        cpuset_ids = set()
        cpuset_reject_ids = set()
        for rule in CONF.vcpu_pin_set.split(','):
            rule = rule.strip()
            # Handle multi ','
            if len(rule) < 1:
                continue
            # Note the count limit in the .split() call
            range_parts = rule.split('-', 1)
            if len(range_parts) > 1:
                # So, this was a range; start by converting the parts to ints
                try:
                    start, end = [int(p.strip()) for p in range_parts]
                except ValueError:
                    raise exception.Invalid(_("Invalid range expression %r")
                                            % rule)
                # Make sure it's a valid range
                if start > end:
                    raise exception.Invalid(_("Invalid range expression %r")
                                            % rule)
                # Add available pcpu ids to set
                cpuset_ids |= set(range(start, end + 1))
            elif rule[0] == '^':
                # Not a range, the rule is an exclusion rule; convert to int
                try:
                    cpuset_reject_ids.add(int(rule[1:].strip()))
                except ValueError:
                    raise exception.Invalid(_("Invalid exclusion "
                                              "expression %r") % rule)
            else:
                # OK, a single PCPU to include; convert to int
                try:
                    cpuset_ids.add(int(rule))
                except ValueError:
                    raise exception.Invalid(_("Invalid inclusion "
                                              "expression %r") % rule)
        # Use sets to handle the exclusion rules for us
        cpuset_ids -= cpuset_reject_ids
        if not cpuset_ids:
            raise exception.Invalid(_("No CPUs available after parsing %r") %
                                    CONF.vcpu_pin_set)
        # This will convert the set to a sorted list for us
        return sorted(cpuset_ids)

    def get_vcpu_total(self):
        """Get available vcpu number of physical computer.

        :returns: the number of cpu core instances can be used.

        """
        if self._vcpu_total != 0:
            return self._vcpu_total

        try:
            total_pcpus = self._conn.getInfo()[2]
        except libvirt.libvirtError:
            LOG.warn(_("Cannot get the number of cpu, because this "
                       "function is not implemented for this platform. "))
            return 0

        if CONF.vcpu_pin_set is None:
            self._vcpu_total = total_pcpus
            return self._vcpu_total

        available_ids = self._get_cpuset_ids()
        if available_ids[-1] >= total_pcpus:
            raise exception.Invalid(_("Invalid vcpu_pin_set config, "
                                      "out of hypervisor cpu range."))
        self._vcpu_total = len(available_ids)
        return self._vcpu_total

    def get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.

        :returns: the total amount of memory(MB).

        """

        return self._conn.getInfo()[1]

    @staticmethod
    def get_local_gb_info():
        """Get local storage info of the compute node in GB.

        :returns: A dict containing:
             :total: How big the overall usable filesystem is (in gigabytes)
             :free: How much space is free (in gigabytes)
             :used: How much space is used (in gigabytes)
        """

        if CONF.libvirt_images_type == 'lvm':
            info = libvirt_utils.get_volume_group_info(
                                 CONF.libvirt_images_volume_group)
        else:
            info = libvirt_utils.get_fs_info(CONF.instances_path)

        for (k, v) in info.iteritems():
            info[k] = v / (1024 ** 3)

        return info

    def get_vcpu_used(self):
        """Get vcpu usage number of physical computer.

        :returns: The total number of vcpu that currently used.

        """

        total = 0
        if CONF.libvirt_type == 'lxc':
            return total + 1

        dom_ids = self.list_instance_ids()
        for dom_id in dom_ids:
            try:
                dom = self._lookup_by_id(dom_id)
                vcpus = dom.vcpus()
                if vcpus is None:
                    LOG.debug(_("couldn't obtain the vpu count from domain id:"
                                " %s") % dom_id)
                else:
                    total += len(vcpus[1])
            except exception.InstanceNotFound:
                LOG.info(_("libvirt can't find a domain with id: %s") % dom_id)
                continue
            # NOTE(gtt116): give change to do other task.
            greenthread.sleep(0)
        return total

    def get_memory_mb_used(self):
        """Get the free memory size(MB) of physical computer.

        :returns: the total usage of memory(MB).

        """

        if sys.platform.upper() not in ['LINUX2', 'LINUX3']:
            return 0

        m = open('/proc/meminfo').read().split()
        idx1 = m.index('MemFree:')
        idx2 = m.index('Buffers:')
        idx3 = m.index('Cached:')
        if CONF.libvirt_type == 'xen':
            used = 0
            for domain_id in self.list_instance_ids():
                try:
                    dom_mem = int(self._lookup_by_id(domain_id).info()[2])
                except exception.InstanceNotFound:
                    LOG.info(_("libvirt can't find a domain with id: %s")
                             % domain_id)
                    continue
                # skip dom0
                if domain_id != 0:
                    used += dom_mem
                else:
                    # the mem reported by dom0 is be greater of what
                    # it is being used
                    used += (dom_mem -
                             (int(m[idx1 + 1]) +
                              int(m[idx2 + 1]) +
                              int(m[idx3 + 1])))
            # Convert it to MB
            return used / 1024
        else:
            avail = (int(m[idx1 + 1]) + int(m[idx2 + 1]) + int(m[idx3 + 1]))
            # Convert it to MB
            return self.get_memory_mb_total() - avail / 1024

    def get_hypervisor_type(self):
        """Get hypervisor type.

        :returns: hypervisor type (ex. qemu)

        """

        return self._conn.getType()

    def get_hypervisor_version(self):
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

    def get_hypervisor_hostname(self):
        """Returns the hostname of the hypervisor."""
        return self._conn.getHostname()

    def get_instance_capabilities(self):
        """Get hypervisor instance capabilities

        Returns a list of tuples that describe instances the
        hypervisor is capable of hosting.  Each tuple consists
        of the triplet (arch, hypervisor_type, vm_mode).

        :returns: List of tuples describing instance capabilities
        """
        caps = self.get_host_capabilities()
        instance_caps = list()
        for g in caps.guests:
            for dt in g.domtype:
                instance_cap = (g.arch, dt, g.ostype)
                instance_caps.append(instance_cap)

        return instance_caps

    def get_cpu_info(self):
        """Get cpuinfo information.

        Obtains cpu feature from virConnect.getCapabilities,
        and returns as a json string.

        :return: see above description

        """

        caps = self.get_host_capabilities()
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
        # so we could just return the raw capabilties XML
        # which 'compare_cpu' could use directly
        #
        # That said, arch_filter.py now seems to rely on
        # the libvirt drivers format which suggests this
        # data format needs to be standardized across drivers
        return jsonutils.dumps(cpu_info)

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

                LOG.debug(_("Trying to get stats for the volume %s"),
                            volume_id)
                vol_stats = self.block_stats(instance['name'], mountpoint)

                if vol_stats:
                    stats = dict(volume=volume_id,
                                 instance=instance,
                                 rd_req=vol_stats[0],
                                 rd_bytes=vol_stats[1],
                                 wr_req=vol_stats[2],
                                 wr_bytes=vol_stats[3],
                                 flush_operations=vol_stats[4])
                    LOG.debug(
                        _("Got volume usage stats for the volume=%(volume)s,"
                          " instance=%(instance)s, rd_req=%(rd_req)d,"
                          " rd_bytes=%(rd_bytes)d, wr_req=%(wr_req)d,"
                          " wr_bytes=%(wr_bytes)d")
                        % stats)
                    vol_usage.append(stats)

        return vol_usage

    def block_stats(self, instance_name, disk):
        """
        Note that this function takes an instance name.
        """
        try:
            domain = self._lookup_by_name(instance_name)
            return domain.blockStats(disk)
        except libvirt.libvirtError as e:
            errcode = e.get_error_code()
            LOG.info(_("Getting block stats failed, device might have "
                       "been detached. Instance=%(instance_name)s "
                       "Disk=%(disk)s Code=%(errcode)s Error=%(e)s")
                       % locals())
        except exception.InstanceNotFound:
            LOG.info(_("Could not find domain in libvirt for instance %s. "
                       "Cannot get block stats for device") % instance_name)

    def interface_stats(self, instance_name, interface):
        """
        Note that this function takes an instance name.
        """
        domain = self._lookup_by_name(instance_name)
        return domain.interfaceStats(interface)

    def get_console_pool_info(self, console_type):
        #TODO(mdragon): console proxy should be implemented for libvirt,
        #               in case someone wants to use it with kvm or
        #               such. For now return fake data.
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
        """Retrieve resource info.

        This method is called as a periodic task and is used only
        in live migration currently.

        :param nodename: ignored in this driver
        :returns: dictionary containing resource info
        """

        def _get_disk_available_least():
            """Return total real disk available least size.

            The size of available disk, when block_migration command given
            disk_over_commit param is FALSE.

            The size that deducted real instance disk size from the total size
            of the virtual disk of all instances.

            """
            disk_free_gb = disk_info_dict['free']
            disk_over_committed = self.get_disk_over_committed_size_total()
            # Disk available least size
            available_least = disk_free_gb * (1024 ** 3) - disk_over_committed
            return (available_least / (1024 ** 3))

        disk_info_dict = self.get_local_gb_info()
        dic = {'vcpus': self.get_vcpu_total(),
               'memory_mb': self.get_memory_mb_total(),
               'local_gb': disk_info_dict['total'],
               'vcpus_used': self.get_vcpu_used(),
               'memory_mb_used': self.get_memory_mb_used(),
               'local_gb_used': disk_info_dict['used'],
               'hypervisor_type': self.get_hypervisor_type(),
               'hypervisor_version': self.get_hypervisor_version(),
               'hypervisor_hostname': self.get_hypervisor_hostname(),
               'cpu_info': self.get_cpu_info(),
               'disk_available_least': _get_disk_available_least()}
        return dic

    def check_instance_shared_storage_local(self, ctxt, instance):
        dirpath = libvirt_utils.get_instance_path(instance)

        if not os.path.exists(dirpath):
            return None

        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug(_("Creating tmpfile %s to verify with other "
                    "compute node that the instance is on "
                    "the same shared storage.") % tmp_file)
        os.close(fd)
        return {"filename": tmp_file}

    def check_instance_shared_storage_remote(self, ctxt, data):
        return os.path.exists(data['filename'])

    def check_instance_shared_storage_cleanup(self, ctxt, data):
        fileutils.delete_if_exists(data["filename"])

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        """Check if it is possible to execute live migration.

        This runs checks on the destination host, and then calls
        back to the source host to check the results.

        :param ctxt: security context
        :param instance_ref: nova.db.sqlalchemy.models.Instance
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
                    (disk_available_gb * 1024) - CONF.reserved_host_disk_mb

        # Compare CPU
        src = instance_ref['host']
        source_cpu_info = src_compute_info['cpu_info']
        self._compare_cpu(source_cpu_info)

        # Create file on storage, to be checked on source host
        filename = self._create_shared_storage_test_file()

        return {"filename": filename,
                "block_migration": block_migration,
                "disk_over_commit": disk_over_commit,
                "disk_available_mb": disk_available_mb}

    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        """Do required cleanup on dest host after check_can_live_migrate calls

        :param ctxt: security context
        """
        filename = dest_check_data["filename"]
        self._cleanup_shared_storage_test_file(filename)

    def check_can_live_migrate_source(self, ctxt, instance, dest_check_data):
        """Check if it is possible to execute live migration.

        This checks if the live migration can succeed, based on the
        results from check_can_live_migrate_destination.

        :param context: security context
        :param instance: nova.db.sqlalchemy.models.Instance
        :param dest_check_data: result of check_can_live_migrate_destination
        :returns: a dict containing migration info
        """
        # Checking shared storage connectivity
        # if block migration, instances_paths should not be on shared storage.
        source = CONF.host
        filename = dest_check_data["filename"]
        block_migration = dest_check_data["block_migration"]
        is_volume_backed = dest_check_data.get('is_volume_backed', False)

        shared = self._check_shared_storage_test_file(filename)

        if block_migration:
            if shared:
                reason = _("Block migration can not be used "
                           "with shared storage.")
                raise exception.InvalidLocalStorage(reason=reason, path=source)
            self._assert_dest_node_has_enough_disk(ctxt, instance,
                                    dest_check_data['disk_available_mb'],
                                    dest_check_data['disk_over_commit'])

        elif not shared and not is_volume_backed:
            reason = _("Live migration can not be used "
                       "without shared storage.")
            raise exception.InvalidSharedStorage(reason=reason, path=source)
        dest_check_data.update({"is_shared_storage": shared})

        # NOTE(mikal): include the instance directory name here because it
        # doesn't yet exist on the destination but we want to force that
        # same name to be used
        instance_path = libvirt_utils.get_instance_path(instance,
                                                        relative=True)
        dest_check_data['instance_relative_path'] = instance_path

        return dest_check_data

    def _assert_dest_node_has_enough_disk(self, context, instance_ref,
                                             available_mb, disk_over_commit):
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
            available = available_mb * (1024 ** 2)

        ret = self.get_instance_disk_info(instance_ref['name'])
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
            instance_uuid = instance_ref['uuid']
            reason = _("Unable to migrate %(instance_uuid)s: "
                       "Disk of instance is too large(available"
                       " on destination host:%(available)s "
                       "< need:%(necessary)s)")
            raise exception.MigrationPreCheckError(reason=reason % locals())

    def _compare_cpu(self, cpu_info):
        """Checks the host cpu is compatible to a cpu given by xml.

        "xml" must be a part of libvirt.openReadonly().getCapabilities().
        return values follows by virCPUCompareResult.
        if 0 > return value, do live migration.
        'http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult'

        :param cpu_info: json string that shows cpu feature(see get_cpu_info())
        :returns:
            None. if given cpu info is not compatible to this server,
            raise exception.
        """

        # NOTE(berendt): virConnectCompareCPU not working for Xen
        if CONF.libvirt_type == 'xen':
            return 1

        info = jsonutils.loads(cpu_info)
        LOG.info(_('Instance launched has CPU info:\n%s') % cpu_info)
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
                ret = e.message
                LOG.error(m % locals())

        if ret <= 0:
            LOG.error(m % locals())
            raise exception.InvalidCPUInfo(reason=m % locals())

    def _create_shared_storage_test_file(self):
        """Makes tmpfile under CONF.instances_path."""
        dirpath = CONF.instances_path
        fd, tmp_file = tempfile.mkstemp(dir=dirpath)
        LOG.debug(_("Creating tmpfile %s to notify to other "
                    "compute nodes that they should mount "
                    "the same storage.") % tmp_file)
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

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info,
                                            time_module=None):
        """Ensure that an instance's filtering rules are enabled.

        When migrating an instance, we need the filtering rules to
        be configured on the destination host before starting the
        migration.

        Also, when restarting the compute service, we need to ensure
        that filtering rules exist for all running services.
        """

        if not time_module:
            time_module = greenthread

        self.firewall_driver.setup_basic_filtering(instance_ref, network_info)
        self.firewall_driver.prepare_instance_filter(instance_ref,
                network_info)

        # nwfilters may be defined in a separate thread in the case
        # of libvirt non-blocking mode, so we wait for completion
        timeout_count = range(CONF.live_migration_retry_count)
        while timeout_count:
            if self.firewall_driver.instance_filter_exists(instance_ref,
                                                           network_info):
                break
            timeout_count.pop()
            if len(timeout_count) == 0:
                msg = _('The firewall filter for %s does not exist')
                raise exception.NovaException(msg % instance_ref["name"])
            time_module.sleep(1)

    def filter_defer_apply_on(self):
        self.firewall_driver.filter_defer_apply_on()

    def filter_defer_apply_off(self):
        self.firewall_driver.filter_defer_apply_off()

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        """Spawning live_migration operation for distributing high-load.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params block_migration: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.
        :params block_migration: if true, do block migration.
        :params migrate_data: implementation specific params

        """

        greenthread.spawn(self._live_migration, ctxt, instance_ref, dest,
                          post_method, recover_method, block_migration,
                          migrate_data)

    def _live_migration(self, ctxt, instance_ref, dest, post_method,
                        recover_method, block_migration=False,
                        migrate_data=None):
        """Do live migration.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.
        :params migrate_data: implementation specific params
        """

        # Do live migration.
        try:
            if block_migration:
                flaglist = CONF.block_migration_flag.split(',')
            else:
                flaglist = CONF.live_migration_flag.split(',')
            flagvals = [getattr(libvirt, x.strip()) for x in flaglist]
            logical_sum = reduce(lambda x, y: x | y, flagvals)

            dom = self._lookup_by_name(instance_ref["name"])
            dom.migrateToURI(CONF.live_migration_uri % dest,
                             logical_sum,
                             None,
                             CONF.live_migration_bandwidth)

        except Exception as e:
            with excutils.save_and_reraise_exception():
                LOG.error(_("Live Migration failure: %(e)s") % locals(),
                          instance=instance_ref)
                recover_method(ctxt, instance_ref, dest, block_migration)

        # Waiting for completion of live_migration.
        timer = loopingcall.FixedIntervalLoopingCall(f=None)

        def wait_for_live_migration():
            """waiting for live migration completion."""
            try:
                self.get_info(instance_ref)['state']
            except exception.NotFound:
                timer.stop()
                post_method(ctxt, instance_ref, dest, block_migration,
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

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, migrate_data=None):
        """Preparation live migration."""
        # Steps for volume backed instance live migration w/o shared storage.
        is_shared_storage = True
        is_volume_backed = False
        is_block_migration = True
        instance_relative_path = None
        if migrate_data:
            is_shared_storage = migrate_data.get('is_shared_storage', True)
            is_volume_backed = migrate_data.get('is_volume_backed', False)
            is_block_migration = migrate_data.get('block_migration', True)
            instance_relative_path = migrate_data.get('instance_relative_path')

        if not is_shared_storage:
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

        if is_volume_backed and not (is_block_migration or is_shared_storage):
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
            disk_dev = vol['mount_device'].rpartition("/")[2]
            disk_info = {
                'dev': disk_dev,
                'bus': blockinfo.get_disk_bus_for_disk_dev(CONF.libvirt_type,
                                                           disk_dev),
                'type': 'disk',
                }
            self.volume_driver_method('connect_volume',
                                      connection_info,
                                      disk_info)

        # We call plug_vifs before the compute manager calls
        # ensure_filtering_rules_for_instance, to ensure bridge is set up
        # Retry operation is necessary because continuously request comes,
        # concorrent request occurs to iptables, then it complains.
        max_retry = CONF.live_migration_retry_count
        for cnt in range(max_retry):
            try:
                self.plug_vifs(instance, network_info)
                break
            except processutils.ProcessExecutionError:
                if cnt == max_retry - 1:
                    raise
                else:
                    LOG.warn(_('plug_vifs() failed %(cnt)d. Retry up to '
                               '%(max_retry)d.'),
                             {'cnt': cnt,
                              'max_retry': max_retry},
                             instance=instance)
                    greenthread.sleep(1)

    def pre_block_migration(self, ctxt, instance, disk_info_json):
        """Preparation for block migration."""
        # NOTE (rmk): When preparing for a block migration, the instance dir
        #             should not exist on the destination hypervisor.
        instance_dir = libvirt_utils.get_instance_path(instance)
        if os.path.exists(instance_dir):
            raise exception.DestinationDiskExists(path=instance_dir)
        os.mkdir(instance_dir)
        self._create_images_and_backing(ctxt, instance, disk_info_json)

    def _create_images_and_backing(self, ctxt, instance, disk_info_json):
        """
        :params ctxt: security context
        :params instance:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params disk_info_json:
            json strings specified in get_instance_disk_info

        """
        disk_info = jsonutils.loads(disk_info_json)
        instance_dir = libvirt_utils.get_instance_path(instance)

        for info in disk_info:
            base = os.path.basename(info['path'])
            # Get image type and create empty disk image, and
            # create backing file in case of qcow2.
            instance_disk = os.path.join(instance_dir, base)
            if not info['backing_file'] and not os.path.exists(instance_disk):
                libvirt_utils.create_image(info['type'], instance_disk,
                                           info['disk_size'])
            else:
                # Creating backing file follows same way as spawning instances.
                cache_name = os.path.basename(info['backing_file'])
                # Remove any size tags which the cache manages
                cache_name = cache_name.split('_')[0]

                image = self.image_backend.image(instance,
                                                 instance_disk,
                                                 CONF.libvirt_images_type)
                image.cache(fetch_func=libvirt_utils.fetch_image,
                            context=ctxt,
                            filename=cache_name,
                            image_id=instance['image_ref'],
                            user_id=instance['user_id'],
                            project_id=instance['project_id'],
                            size=info['virt_disk_size'])

        # if image has kernel and ramdisk, just download
        # following normal way.
        self._fetch_instance_kernel_ramdisk(ctxt, instance)

    def post_live_migration_at_destination(self, ctxt,
                                           instance_ref,
                                           network_info,
                                           block_migration,
                                           block_device_info=None):
        """Post operation of live migration at destination host.

        :param ctxt: security context
        :param instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :param network_info: instance network information
        :param block_migration: if true, post operation of block_migraiton.
        """
        # Define migrated instance, otherwise, suspend/destroy does not work.
        dom_list = self._conn.listDefinedDomains()
        if instance_ref["name"] not in dom_list:
            # In case of block migration, destination does not have
            # libvirt.xml
            disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                                instance_ref)
            self.to_xml(instance_ref, network_info, disk_info,
                        block_device_info, write_to_disk=True)
            # libvirt.xml should be made by to_xml(), but libvirt
            # does not accept to_xml() result, since uuid is not
            # included in to_xml() result.
            dom = self._lookup_by_name(instance_ref["name"])
            self._conn.defineXML(dom.XMLDesc(0))

    def get_instance_disk_info(self, instance_name, xml=None):
        """Preparation block migration.

        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :return:
            json strings with below format::

                "[{'path':'disk', 'type':'raw',
                  'virt_disk_size':'10737418240',
                  'backing_file':'backing_file',
                  'disk_size':'83886080'},...]"

        """
        # NOTE (rmk): Passing the domain XML into this function is optional.
        #             When it is not passed, we attempt to extract it from
        #             the pre-existing definition.
        if xml is None:
            try:
                virt_dom = self._lookup_by_name(instance_name)
                xml = virt_dom.XMLDesc(0)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                msg = _("Error from libvirt while getting description of "
                        "%(instance_name)s: [Error Code %(error_code)s] "
                        "%(ex)s") % locals()
                LOG.warn(msg)
                raise exception.InstanceNotFound(instance_id=instance_name)

        disk_info = []
        doc = etree.fromstring(xml)
        disk_nodes = doc.findall('.//devices/disk')
        path_nodes = doc.findall('.//devices/disk/source')
        driver_nodes = doc.findall('.//devices/disk/driver')

        for cnt, path_node in enumerate(path_nodes):
            disk_type = disk_nodes[cnt].get('type')
            path = path_node.get('file')

            if disk_type != 'file':
                LOG.debug(_('skipping %(path)s since it looks like volume') %
                          locals())
                continue

            if not path:
                LOG.debug(_('skipping disk for %(instance_name)s as it'
                            ' does not have a path') %
                          locals())
                continue

            # get the real disk size or
            # raise a localized error if image is unavailable
            dk_size = int(os.path.getsize(path))

            disk_type = driver_nodes[cnt].get('type')
            if disk_type == "qcow2":
                backing_file = libvirt_utils.get_disk_backing_file(path)
                virt_size = disk.get_disk_size(path)
                over_commit_size = int(virt_size) - dk_size
            else:
                backing_file = ""
                virt_size = 0
                over_commit_size = 0

            disk_info.append({'type': disk_type,
                              'path': path,
                              'virt_disk_size': virt_size,
                              'backing_file': backing_file,
                              'disk_size': dk_size,
                              'over_committed_disk_size': over_commit_size})
        return jsonutils.dumps(disk_info)

    def get_disk_over_committed_size_total(self):
        """Return total over committed disk size for all instances."""
        # Disk size that all instance uses : virtual_size - disk_size
        instances_name = self.list_instances()
        disk_over_committed_size = 0
        for i_name in instances_name:
            try:
                disk_infos = jsonutils.loads(
                        self.get_instance_disk_info(i_name))
                for info in disk_infos:
                    disk_over_committed_size += int(
                        info['over_committed_disk_size'])
            except OSError as e:
                if e.errno == errno.ENOENT:
                    LOG.error(_("Getting disk size of %(i_name)s: %(e)s") %
                              locals())
                else:
                    raise
            except exception.InstanceNotFound:
                # Instance was deleted during the check so ignore it
                pass
            # NOTE(gtt116): give change to do other task.
            greenthread.sleep(0)
        return disk_over_committed_size

    def unfilter_instance(self, instance_ref, network_info):
        """See comments of same method in firewall_driver."""
        self.firewall_driver.unfilter_instance(instance_ref,
                                               network_info=network_info)

    def get_host_stats(self, refresh=False):
        """Return the current state of the host.

        If 'refresh' is True, run update the stats first.
        """
        return self.host_state.get_host_stats(refresh=refresh)

    def get_host_uptime(self, host):
        """Returns the result of calling "uptime"."""
        #NOTE(dprince): host seems to be ignored for this call and in
        # other compute drivers as well. Perhaps we should remove it?
        out, err = utils.execute('env', 'LANG=C', 'uptime')
        return out

    def manage_image_cache(self, context, all_instances):
        """Manage the local cache of images."""
        self.image_cache_manager.verify_base_images(context, all_instances)

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
                                   instance_type, network_info,
                                   block_device_info=None):
        LOG.debug(_("Starting migrate_disk_and_power_off"),
                   instance=instance)
        disk_info_text = self.get_instance_disk_info(instance['name'])
        disk_info = jsonutils.loads(disk_info_text)

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

        self.power_off(instance)

        block_device_mapping = driver.block_device_info_get_mapping(
            block_device_info)
        for vol in block_device_mapping:
            connection_info = vol['connection_info']
            disk_dev = vol['mount_device'].rpartition("/")[2]
            self.volume_driver_method('disconnect_volume',
                                      connection_info,
                                      disk_dev)

        try:
            utils.execute('mv', inst_base, inst_base_resize)
            # if we are migrating the instance with shared storage then
            # create the directory.  If it is a remote node the directory
            # has already been created
            if shared_storage:
                dest = None
                utils.execute('mkdir', '-p', inst_base)
            for info in disk_info:
                # assume inst_base == dirname(info['path'])
                img_path = info['path']
                fname = os.path.basename(img_path)
                from_path = os.path.join(inst_base_resize, fname)
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
        state = self.get_info(instance)['state']

        if state == power_state.RUNNING:
            LOG.info(_("Instance running successfully."), instance=instance)
            raise loopingcall.LoopingCallDone()

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        LOG.debug(_("Starting finish_migration"), instance=instance)

        # resize disks. only "disk" and "disk.local" are necessary.
        disk_info = jsonutils.loads(disk_info)
        for info in disk_info:
            fname = os.path.basename(info['path'])
            if fname == 'disk':
                size = instance['root_gb']
            elif fname == 'disk.local':
                size = instance['ephemeral_gb']
            else:
                size = 0
            size *= 1024 * 1024 * 1024

            # If we have a non partitioned image that we can extend
            # then ensure we're in 'raw' format so we can extend file system.
            fmt = info['type']
            if (size and fmt == 'qcow2' and
                disk.can_resize_fs(info['path'], size, use_cow=True)):
                path_raw = info['path'] + '_raw'
                utils.execute('qemu-img', 'convert', '-f', 'qcow2',
                              '-O', 'raw', info['path'], path_raw)
                utils.execute('mv', path_raw, info['path'])
                fmt = 'raw'

            if size:
                disk.extend(info['path'], size)

            if fmt == 'raw' and CONF.use_cow_images:
                # back to qcow2 (no backing_file though) so that snapshot
                # will be available
                path_qcow = info['path'] + '_qcow'
                utils.execute('qemu-img', 'convert', '-f', 'raw',
                              '-O', 'qcow2', info['path'], path_qcow)
                utils.execute('mv', path_qcow, info['path'])

        disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                            instance,
                                            block_device_info,
                                            image_meta)
        # assume _create_image do nothing if a target file exists.
        # TODO(oda): injecting files is not necessary
        self._create_image(context, instance,
                           disk_mapping=disk_info['mapping'],
                           network_info=network_info,
                           block_device_info=None)
        xml = self.to_xml(instance, network_info, disk_info,
                          block_device_info=block_device_info,
                          write_to_disk=True)
        self._create_domain_and_network(xml, instance, network_info,
                                        block_device_info, power_on)
        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

    def _cleanup_failed_migration(self, inst_base):
        """Make sure that a failed migrate doesn't prevent us from rolling
        back in a revert.
        """
        shutil.rmtree(inst_base)

    def finish_revert_migration(self, instance, network_info,
                                block_device_info=None, power_on=True):
        LOG.debug(_("Starting finish_revert_migration"),
                   instance=instance)

        inst_base = libvirt_utils.get_instance_path(instance)
        inst_base_resize = inst_base + "_resize"

        # NOTE(danms): if we're recovering from a failed migration,
        # make sure we don't have a left-over same-host base directory
        # that would conflict. Also, don't fail on the rename if the
        # failure happened early.
        if os.path.exists(inst_base_resize):
            if os.path.exists(inst_base):
                self._cleanup_failed_migration(inst_base)
            utils.execute('mv', inst_base_resize, inst_base)

        disk_info = blockinfo.get_disk_info(CONF.libvirt_type,
                                            instance,
                                            block_device_info)
        xml = self.to_xml(instance, network_info, disk_info,
                          block_device_info=block_device_info)
        self._create_domain_and_network(xml, instance, network_info,
                                        block_device_info, power_on)

        if power_on:
            timer = loopingcall.FixedIntervalLoopingCall(
                                                    self._wait_for_running,
                                                    instance)
            timer.start(interval=0.5).wait()

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""
        self._cleanup_resize(instance, network_info)

    def get_diagnostics(self, instance):
        def get_io_devices(xml_doc):
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

        domain = self._lookup_by_name(instance['name'])
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
        dom_io = get_io_devices(xml)
        for disk in dom_io["volumes"]:
            try:
                # blockStats might launch an exception if the method
                # is not supported by the underlying hypervisor being
                # used by libvirt
                stats = domain.blockStats(disk)
                output[disk + "_read_req"] = stats[0]
                output[disk + "_read"] = stats[1]
                output[disk + "_write_req"] = stats[2]
                output[disk + "_write"] = stats[3]
                output[disk + "_errors"] = stats[4]
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

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        """Add a compute host to an aggregate."""
        #NOTE(jogo) Currently only used for XenAPI-Pool
        pass

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        """Remove a compute host from an aggregate."""
        pass

    def undo_aggregate_operation(self, context, op, aggregate,
                                  host, set_error=True):
        """only used for Resource Pools."""
        pass

    def instance_on_disk(self, instance):
        # ensure directories exist and are writable
        instance_path = libvirt_utils.get_instance_path(instance)
        LOG.debug(_('Checking instance files accessability'
                   '%(instance_path)s')
                 % locals())
        return os.access(instance_path, os.W_OK)

    def inject_network_info(self, instance, nw_info):
        self.firewall_driver.setup_basic_filtering(instance, nw_info)


class HostState(object):
    """Manages information about the compute node through libvirt."""
    def __init__(self, driver):
        super(HostState, self).__init__()
        self._stats = {}
        self.driver = driver
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_status()
        return self._stats

    def update_status(self):
        """Retrieve status info from libvirt."""
        LOG.debug(_("Updating host stats"))
        data = {}
        data["vcpus"] = self.driver.get_vcpu_total()
        data["vcpus_used"] = self.driver.get_vcpu_used()
        data["cpu_info"] = jsonutils.loads(self.driver.get_cpu_info())
        disk_info_dict = self.driver.get_local_gb_info()
        data["disk_total"] = disk_info_dict['total']
        data["disk_used"] = disk_info_dict['used']
        data["disk_available"] = disk_info_dict['free']
        data["host_memory_total"] = self.driver.get_memory_mb_total()
        data["host_memory_free"] = (data["host_memory_total"] -
                                    self.driver.get_memory_mb_used())
        data["hypervisor_type"] = self.driver.get_hypervisor_type()
        data["hypervisor_version"] = self.driver.get_hypervisor_version()
        data["hypervisor_hostname"] = self.driver.get_hypervisor_hostname()
        data["supported_instances"] = \
            self.driver.get_instance_capabilities()

        self._stats = data

        return data
