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
Manages information about the host OS and hypervisor.

This class encapsulates a connection to the libvirt
daemon and provides certain higher level APIs around
the raw libvirt API. These APIs are then used by all
the other libvirt related classes
"""

from collections import defaultdict
import inspect
import operator
import os
import socket
import threading
import traceback

from eventlet import greenio
from eventlet import greenthread
from eventlet import patcher
from eventlet import tpool
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import units
from oslo_utils import versionutils
import six

from nova.compute import utils as compute_utils
import nova.conf
from nova import context as nova_context
from nova import exception
from nova.i18n import _
from nova import rpc
from nova import utils
from nova.virt import event as virtevent
from nova.virt.libvirt import config as vconfig
from nova.virt.libvirt import guest as libvirt_guest
from nova.virt.libvirt import migration as libvirt_migrate
from nova.virt.libvirt import utils as libvirt_utils

libvirt = None

LOG = logging.getLogger(__name__)

native_socket = patcher.original('socket')
native_threading = patcher.original("threading")
native_Queue = patcher.original("Queue" if six.PY2 else "queue")

CONF = nova.conf.CONF


# This list is for libvirt hypervisor drivers that need special handling.
# This is *not* the complete list of supported hypervisor drivers.
HV_DRIVER_QEMU = "QEMU"
HV_DRIVER_XEN = "Xen"

SEV_KERNEL_PARAM_FILE = '/sys/module/kvm_amd/parameters/sev'


class Host(object):

    def __init__(self, uri, read_only=False,
                 conn_event_handler=None,
                 lifecycle_event_handler=None):

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')

        self._uri = uri
        self._read_only = read_only
        self._initial_connection = True
        self._conn_event_handler = conn_event_handler
        self._conn_event_handler_queue = six.moves.queue.Queue()
        self._lifecycle_event_handler = lifecycle_event_handler
        self._caps = None
        self._domain_caps = None
        self._hostname = None

        self._wrapped_conn = None
        self._wrapped_conn_lock = threading.Lock()
        self._event_queue = None

        self._events_delayed = {}
        # Note(toabctl): During a reboot of a domain, STOPPED and
        #                STARTED events are sent. To prevent shutting
        #                down the domain during a reboot, delay the
        #                STOPPED lifecycle event some seconds.
        self._lifecycle_delay = 15

        self._initialized = False
        self._libvirt_proxy_classes = self._get_libvirt_proxy_classes(libvirt)
        self._libvirt_proxy = self._wrap_libvirt_proxy(libvirt)

        # AMD SEV is conditional on support in the hardware, kernel,
        # qemu, and libvirt.  This is determined on demand and
        # memoized by the supports_amd_sev property below.
        self._supports_amd_sev = None

        self._has_hyperthreading = None

    @staticmethod
    def _get_libvirt_proxy_classes(libvirt_module):
        """Return a tuple for tpool.Proxy's autowrap argument containing all
        classes defined by the libvirt module except libvirtError.
        """

        # Get a list of (name, class) tuples of libvirt classes
        classes = inspect.getmembers(libvirt_module, inspect.isclass)

        # Return a list of just the classes, filtering out libvirtError because
        # we don't need to proxy that
        return tuple([cls[1] for cls in classes if cls[0] != 'libvirtError'])

    def _wrap_libvirt_proxy(self, obj):
        """Return an object wrapped in a tpool.Proxy using autowrap appropriate
        for the libvirt module.
        """

        # libvirt is not pure python, so eventlet monkey patching doesn't work
        # on it. Consequently long-running libvirt calls will not yield to
        # eventlet's event loop, starving all other greenthreads until
        # completion. eventlet's tpool.Proxy handles this situation for us by
        # executing proxied calls in a native thread.
        return tpool.Proxy(obj, autowrap=self._libvirt_proxy_classes)

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

    def _conn_event_thread(self):
        """Dispatches async connection events"""
        # NOTE(mdbooth): This thread doesn't need to jump through the same
        # hoops as _dispatch_thread because it doesn't interact directly
        # with the libvirt native thread.
        while True:
            self._dispatch_conn_event()

    def _dispatch_conn_event(self):
        # NOTE(mdbooth): Splitting out this loop looks redundant, but it
        # means we can easily dispatch events synchronously from tests and
        # it isn't completely awful.
        handler = self._conn_event_handler_queue.get()
        try:
            handler()
        except Exception:
            LOG.exception(_('Exception handling connection event'))
        finally:
            self._conn_event_handler_queue.task_done()

    @staticmethod
    def _event_lifecycle_callback(conn, dom, event, detail, opaque):
        """Receives lifecycle events from libvirt.

        NB: this method is executing in a native thread, not
        an eventlet coroutine. It can only invoke other libvirt
        APIs, or use self._queue_event(). Any use of logging APIs
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
            if detail == libvirt.VIR_DOMAIN_EVENT_SUSPENDED_POSTCOPY:
                transition = virtevent.EVENT_LIFECYCLE_POSTCOPY_STARTED
            elif detail == libvirt.VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED:
                # VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED is also sent when live
                # migration of the guest fails, so we cannot simply rely
                # on the event itself but need to check if the job itself was
                # successful.
                # NOTE(mriedem): The job check logic here is copied from
                # LibvirtDriver._live_migration_monitor.
                guest = libvirt_guest.Guest(dom)
                info = guest.get_job_info()
                if info.type == libvirt.VIR_DOMAIN_JOB_NONE:
                    # Either still running, or failed or completed,
                    # lets untangle the mess.
                    info.type = libvirt_migrate.find_job_type(
                        guest, instance=None, logging_ok=False)

                if info.type == libvirt.VIR_DOMAIN_JOB_COMPLETED:
                    transition = virtevent.EVENT_LIFECYCLE_MIGRATION_COMPLETED
                else:
                    # Failed or some other status we don't know about, so just
                    # opt to report the guest is paused.
                    transition = virtevent.EVENT_LIFECYCLE_PAUSED
            else:
                transition = virtevent.EVENT_LIFECYCLE_PAUSED
        elif event == libvirt.VIR_DOMAIN_EVENT_RESUMED:
            transition = virtevent.EVENT_LIFECYCLE_RESUMED

        if transition is not None:
            self._queue_event(virtevent.LifecycleEvent(uuid, transition))

    def _close_callback(self, conn, reason, opaque):
        close_info = {'conn': conn, 'reason': reason}
        self._queue_event(close_info)

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
                LOG.debug('Connection to libvirt broke')
                return False
            raise

    @staticmethod
    def _connect_auth_cb(creds, opaque):
        if len(creds) == 0:
            return 0
        raise exception.InternalError(
            _("Can not handle authentication request for %d credentials")
            % len(creds))

    def _connect(self, uri, read_only):
        auth = [[libvirt.VIR_CRED_AUTHNAME,
                 libvirt.VIR_CRED_ECHOPROMPT,
                 libvirt.VIR_CRED_REALM,
                 libvirt.VIR_CRED_PASSPHRASE,
                 libvirt.VIR_CRED_NOECHOPROMPT,
                 libvirt.VIR_CRED_EXTERNAL],
                Host._connect_auth_cb,
                None]

        flags = 0
        if read_only:
            flags = libvirt.VIR_CONNECT_RO
        return self._libvirt_proxy.openAuth(uri, auth, flags)

    def _queue_event(self, event):
        """Puts an event on the queue for dispatch.

        This method is called by the native event thread to
        put events on the queue for later dispatch by the
        green thread. Any use of logging APIs is forbidden.
        """

        if self._event_queue is None:
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
        last_close_event = None
        while not self._event_queue.empty():
            try:
                event = self._event_queue.get(block=False)
                if isinstance(event, virtevent.LifecycleEvent):
                    # call possibly with delay
                    self._event_emit_delayed(event)

                elif 'conn' in event and 'reason' in event:
                    last_close_event = event
            except native_Queue.Empty:
                pass
        if last_close_event is None:
            return
        conn = last_close_event['conn']
        # get_new_connection may already have disabled the host,
        # in which case _wrapped_conn is None.
        with self._wrapped_conn_lock:
            if conn == self._wrapped_conn:
                reason = str(last_close_event['reason'])
                msg = _("Connection to libvirt lost: %s") % reason
                self._wrapped_conn = None
                self._queue_conn_event_handler(False, msg)

    def _event_emit_delayed(self, event):
        """Emit events - possibly delayed."""
        def event_cleanup(gt, *args, **kwargs):
            """Callback function for greenthread. Called
            to cleanup the _events_delayed dictionary when an event
            was called.
            """
            event = args[0]
            self._events_delayed.pop(event.uuid, None)

        # Cleanup possible delayed stop events.
        if event.uuid in self._events_delayed.keys():
            self._events_delayed[event.uuid].cancel()
            self._events_delayed.pop(event.uuid, None)
            LOG.debug("Removed pending event for %s due to "
                      "lifecycle event", event.uuid)

        if event.transition == virtevent.EVENT_LIFECYCLE_STOPPED:
            # Delay STOPPED event, as they may be followed by a STARTED
            # event in case the instance is rebooting
            id_ = greenthread.spawn_after(self._lifecycle_delay,
                                          self._event_emit, event)
            self._events_delayed[event.uuid] = id_
            # add callback to cleanup self._events_delayed dict after
            # event was called
            id_.link(event_cleanup, event)
        else:
            self._event_emit(event)

    def _event_emit(self, event):
        if self._lifecycle_event_handler is not None:
            self._lifecycle_event_handler(event)

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
            sock = native_socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('localhost', 0))
            sock.listen(50)
            csock = native_socket.socket(socket.AF_INET, socket.SOCK_STREAM)
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
        self._event_thread = native_threading.Thread(
            target=self._native_thread)
        self._event_thread.setDaemon(True)
        self._event_thread.start()

        LOG.debug("Starting green dispatch thread")
        utils.spawn(self._dispatch_thread)

    def _get_new_connection(self):
        # call with _wrapped_conn_lock held
        LOG.debug('Connecting to libvirt: %s', self._uri)

        # This will raise an exception on failure
        wrapped_conn = self._connect(self._uri, self._read_only)

        try:
            LOG.debug("Registering for lifecycle events %s", self)
            wrapped_conn.domainEventRegisterAny(
                None,
                libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._event_lifecycle_callback,
                self)
        except Exception as e:
            LOG.warning("URI %(uri)s does not support events: %(error)s",
                        {'uri': self._uri, 'error': e})

        try:
            LOG.debug("Registering for connection events: %s", str(self))
            wrapped_conn.registerCloseCallback(self._close_callback, None)
        except libvirt.libvirtError as e:
            LOG.warning("URI %(uri)s does not support connection"
                        " events: %(error)s",
                        {'uri': self._uri, 'error': e})

        return wrapped_conn

    def _queue_conn_event_handler(self, *args, **kwargs):
        if self._conn_event_handler is None:
            return

        def handler():
            return self._conn_event_handler(*args, **kwargs)

        self._conn_event_handler_queue.put(handler)

    def _get_connection(self):
        # multiple concurrent connections are protected by _wrapped_conn_lock
        with self._wrapped_conn_lock:
            # Drop the existing connection if it is not usable
            if (self._wrapped_conn is not None and
                    not self._test_connection(self._wrapped_conn)):
                self._wrapped_conn = None
                # Connection was previously up, and went down
                self._queue_conn_event_handler(
                    False, _('Connection to libvirt lost'))

            if self._wrapped_conn is None:
                try:
                    # This will raise if it fails to get a connection
                    self._wrapped_conn = self._get_new_connection()
                except Exception as ex:
                    with excutils.save_and_reraise_exception():
                        # If we previously had a connection and it went down,
                        # we generated a down event for that above.
                        # We also want to generate a down event for an initial
                        # failure, which won't be handled above.
                        if self._initial_connection:
                            self._queue_conn_event_handler(
                                False,
                                _('Failed to connect to libvirt: %(msg)s') %
                                {'msg': ex})
                finally:
                    self._initial_connection = False

                self._queue_conn_event_handler(True, None)

        return self._wrapped_conn

    def get_connection(self):
        """Returns a connection to the hypervisor

        This method should be used to create and return a well
        configured connection to the hypervisor.

        :returns: a libvirt.virConnect object
        """
        try:
            conn = self._get_connection()
        except libvirt.libvirtError as ex:
            LOG.exception(_("Connection to libvirt failed: %s"), ex)
            payload = dict(ip=CONF.my_ip,
                           method='_connect',
                           reason=ex)
            ctxt = nova_context.get_admin_context()
            rpc.get_notifier('compute').error(ctxt,
                                              'compute.libvirt.error',
                                              payload)
            compute_utils.notify_about_libvirt_connect_error(
                ctxt, ip=CONF.my_ip, exception=ex, tb=traceback.format_exc())
            raise exception.HypervisorUnavailable()

        return conn

    @staticmethod
    def _libvirt_error_handler(context, err):
        # Just ignore instead of default outputting to stderr.
        pass

    def initialize(self):
        if self._initialized:
            return

        # NOTE(dkliban): Error handler needs to be registered before libvirt
        #                connection is used for the first time.  Otherwise, the
        #                handler does not get registered.
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)
        libvirt.virEventRegisterDefaultImpl()
        self._init_events()

        LOG.debug("Starting connection event dispatch thread")
        utils.spawn(self._conn_event_thread)

        self._initialized = True

    def _version_check(self, lv_ver=None, hv_ver=None, hv_type=None,
                       op=operator.lt):
        """Check libvirt version, hypervisor version, and hypervisor type

        :param hv_type: hypervisor driver from the top of this file.
        """
        conn = self.get_connection()
        try:
            if lv_ver is not None:
                libvirt_version = conn.getLibVersion()
                if op(libvirt_version,
                      versionutils.convert_version_to_int(lv_ver)):
                    return False

            if hv_ver is not None:
                hypervisor_version = conn.getVersion()
                if op(hypervisor_version,
                      versionutils.convert_version_to_int(hv_ver)):
                    return False

            if hv_type is not None:
                hypervisor_type = conn.getType()
                if hypervisor_type != hv_type:
                    return False

            return True
        except Exception:
            return False

    def has_min_version(self, lv_ver=None, hv_ver=None, hv_type=None):
        return self._version_check(
            lv_ver=lv_ver, hv_ver=hv_ver, hv_type=hv_type, op=operator.lt)

    def has_version(self, lv_ver=None, hv_ver=None, hv_type=None):
        return self._version_check(
            lv_ver=lv_ver, hv_ver=hv_ver, hv_type=hv_type, op=operator.ne)

    def get_guest(self, instance):
        """Retrieve libvirt guest object for an instance.

        All libvirt error handling should be handled in this method and
        relevant nova exceptions should be raised in response.

        :param instance: a nova.objects.Instance object

        :returns: a nova.virt.libvirt.Guest object
        :raises exception.InstanceNotFound: The domain was not found
        :raises exception.InternalError: A libvirt error occurred
        """
        return libvirt_guest.Guest(self._get_domain(instance))

    def _get_domain(self, instance):
        """Retrieve libvirt domain object for an instance.

        All libvirt error handling should be handled in this method and
        relevant nova exceptions should be raised in response.

        :param instance: a nova.objects.Instance object

        :returns: a libvirt.Domain object
        :raises exception.InstanceNotFound: The domain was not found
        :raises exception.InternalError: A libvirt error occurred
        """
        try:
            conn = self.get_connection()
            return conn.lookupByUUIDString(instance.uuid)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance.uuid)

            msg = (_('Error from libvirt while looking up %(instance_name)s: '
                     '[Error Code %(error_code)s] %(ex)s') %
                   {'instance_name': instance.name,
                    'error_code': error_code,
                    'ex': ex})
            raise exception.InternalError(msg)

    def list_guests(self, only_running=True, only_guests=True):
        """Get a list of Guest objects for nova instances

        :param only_running: True to only return running instances
        :param only_guests: True to filter out any host domain (eg Dom-0)

        See method "list_instance_domains" for more information.

        :returns: list of Guest objects
        """
        return [libvirt_guest.Guest(dom) for dom in self.list_instance_domains(
            only_running=only_running, only_guests=only_guests)]

    def list_instance_domains(self, only_running=True, only_guests=True):
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
        flags = libvirt.VIR_CONNECT_LIST_DOMAINS_ACTIVE
        if not only_running:
            flags = flags | libvirt.VIR_CONNECT_LIST_DOMAINS_INACTIVE

        # listAllDomains() returns <list of virDomain>, not <virDomain>, so
        # tpool.Proxy's autowrap won't catch it. We need to wrap the
        # contents of the list we return.
        alldoms = (self._wrap_libvirt_proxy(dom)
                   for dom in self.get_connection().listAllDomains(flags))

        doms = []
        for dom in alldoms:
            if only_guests and dom.ID() == 0:
                continue
            doms.append(dom)

        return doms

    def get_online_cpus(self):
        """Get the set of CPUs that are online on the host

        :returns: set of online CPUs, raises libvirtError on error
        """
        cpus, cpu_map, online = self.get_connection().getCPUMap()

        online_cpus = set()
        for cpu in range(cpus):
            if cpu_map[cpu]:
                online_cpus.add(cpu)

        return online_cpus

    def get_cpu_model_names(self):
        """Get the cpu models based on host CPU arch

        :returns: a list of cpu models which supported by the given CPU arch
        """
        arch = self.get_capabilities().host.cpu.arch
        return self.get_connection().getCPUModelNames(arch)

    @staticmethod
    def _log_host_capabilities(xmlstr):
        # NOTE(mriedem): This looks a bit weird but we do this so we can stub
        # out this method in unit/functional test runs since the xml string is
        # big and it can cause subunit parsing to fail (see bug 1813147).
        LOG.info("Libvirt host capabilities %s", xmlstr)

    def get_capabilities(self):
        """Returns the host capabilities information

        Returns an instance of config.LibvirtConfigCaps representing
        the capabilities of the host.

        Note: The result is cached in the member attribute _caps.

        :returns: a config.LibvirtConfigCaps object
        """
        if not self._caps:
            xmlstr = self.get_connection().getCapabilities()
            self._log_host_capabilities(xmlstr)
            self._caps = vconfig.LibvirtConfigCaps()
            self._caps.parse_str(xmlstr)
            # NOTE(mriedem): Don't attempt to get baseline CPU features
            # if libvirt can't determine the host cpu model.
            if (hasattr(libvirt,
                        'VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES') and
                    self._caps.host.cpu.model is not None):
                try:
                    xml_str = self._caps.host.cpu.to_xml()
                    if six.PY3 and isinstance(xml_str, six.binary_type):
                        xml_str = xml_str.decode('utf-8')
                    features = self.get_connection().baselineCPU(
                        [xml_str],
                        libvirt.VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES)
                    if features:
                        cpu = vconfig.LibvirtConfigCPU()
                        cpu.parse_str(features)
                        self._caps.host.cpu.features = cpu.features
                except libvirt.libvirtError as ex:
                    error_code = ex.get_error_code()
                    if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                        LOG.warning("URI %(uri)s does not support full set"
                                    " of host capabilities: %(error)s",
                                     {'uri': self._uri, 'error': ex})
                    else:
                        raise
        return self._caps

    def get_domain_capabilities(self):
        """Returns the capabilities you can request when creating a
        domain (VM) with that hypervisor, for various combinations of
        architecture and machine type.

        In this context the fuzzy word "hypervisor" implies QEMU
        binary, libvirt itself and the host config.  libvirt provides
        this in order that callers can determine what the underlying
        emulator and/or libvirt is capable of, prior to creating a domain
        (for instance via virDomainCreateXML or virDomainDefineXML).
        However nova needs to know the capabilities much earlier, when
        the host's compute service is first initialised, in order that
        placement decisions can be made across many compute hosts.
        Therefore this is expected to be called during the init_host()
        phase of the driver lifecycle rather than just before booting
        an instance.

        This causes an additional complication since the Python
        binding for this libvirt API call requires the architecture
        and machine type to be provided.  So in order to gain a full
        picture of the hypervisor's capabilities, technically we need
        to call it with the right parameters, once for each
        (architecture, machine_type) combination which we care about.
        However the libvirt experts have advised us that in practice
        the domain capabilities do not (yet, at least) vary enough
        across machine types to justify the cost of calling
        getDomainCapabilities() once for every single (architecture,
        machine_type) combination.  In particular, SEV support isn't
        reported per-machine type, and since there are usually many
        machine types, we heed the advice of the experts that it's
        typically sufficient to call it once per host architecture:

            https://bugzilla.redhat.com/show_bug.cgi?id=1683471#c7

        However, that's not quite sufficient in the context of nova,
        because SEV guests typically require a q35 machine type, as do
        KVM/QEMU guests that want Secure Boot, whereas the current
        default machine type for x86_64 is 'pc'.  So we need results
        from the getDomainCapabilities API for at least those two.
        Fortunately we can take advantage of the results from the
        getCapabilities API which marks selected machine types as
        canonical, e.g.:

            <machine canonical='pc-i440fx-2.11' maxCpus='255'>pc</machine>
            <machine canonical='pc-q35-2.11' maxCpus='288'>q35</machine>

        So for now, we call getDomainCapabilities for these canonical
        machine types of each architecture, plus for the
        architecture's default machine type, if that is not one of the
        canonical types.

        Future domain capabilities might report SEV in a more
        fine-grained manner, and we also expect to use this method to
        detect other features, such as for gracefully handling machine
        types and potentially for detecting OVMF binaries.  Therefore
        we memoize the results of the API calls in a nested dict where
        the top-level keys are architectures, and second-level keys
        are machine types, in order to allow easy expansion later.

        Whenever libvirt/QEMU are updated, cached domCapabilities
        would get outdated (because QEMU will contain new features and
        the capabilities will vary).  However, this should not be a
        problem here, because when libvirt/QEMU gets updated, the
        nova-compute agent also needs restarting, at which point the
        memoization will vanish because it's not persisted to disk.

        Note: The result is cached in the member attribute
        _domain_caps.

        :returns: a nested dict of dicts which maps architectures to
        machine types to instances of config.LibvirtConfigDomainCaps
        representing the domain capabilities of the host for that arch
        and machine type:

        { arch:
          { machine_type: LibvirtConfigDomainCaps }
        }
        """
        if self._domain_caps:
            return self._domain_caps

        domain_caps = defaultdict(dict)
        caps = self.get_capabilities()
        virt_type = CONF.libvirt.virt_type

        for guest in caps.guests:
            arch = guest.arch
            domain = guest.domains.get(virt_type, guest.default_domain)

            for machine_type in self._get_machine_types(arch, domain):
                # It is expected that if there are multiple <guest>
                # elements, each will have a different architecture;
                # for example, on x86 hosts one <guest> will contain
                # <arch name='i686'> and one will contain <arch
                # name='x86_64'>. But it doesn't hurt to add a safety
                # net to avoid needlessly calling libvirt's API more
                # times than we need.
                if machine_type and machine_type in domain_caps[arch]:
                    continue
                self._add_to_domain_capabilities(domain.emulator, arch,
                                                 domain_caps, machine_type,
                                                 virt_type)

        # NOTE(aspiers): Use a temporary variable to update the
        # instance variable atomically, otherwise if some API
        # calls succeeded and then one failed, we might
        # accidentally memoize a partial result.
        self._domain_caps = domain_caps

        return self._domain_caps

    def _get_machine_types(self, arch, domain):
        """Get the machine types for this architecture for which we need to
        call getDomainCapabilities, i.e. the canonical machine types,
        and the default machine type (if it's not one of the canonical
        machine types).

        See the docstring for get_domain_capabilities() for an explanation
        of why we choose this set of machine types.
        """
        # NOTE(aspiers): machine_type could be None here if nova
        # doesn't have a default machine type for this architecture.
        # See _add_to_domain_capabilities() below for how this is handled.
        mtypes = set([libvirt_utils.get_default_machine_type(arch)])
        mtypes.update(domain.aliases.keys())
        LOG.debug("Getting domain capabilities for %(arch)s via "
                  "machine types: %(mtypes)s",
                  {'arch': arch, 'mtypes': mtypes})
        return mtypes

    def _add_to_domain_capabilities(self, emulator_bin, arch, domain_caps,
                                    machine_type, virt_type):
        # NOTE(aspiers): machine_type could be None here if nova
        # doesn't have a default machine type for this architecture.
        # In that case we pass a machine_type of None to the libvirt
        # API and rely on it choosing a sensible default which will be
        # returned in the <machine> element.  It could also be an
        # alias like 'pc' rather than a full machine type.
        #
        # NOTE(kchamart): Prior to libvirt v4.7.0 libvirt picked its
        # default machine type for x86, 'pc', as reported by QEMU's
        # default.  From libvirt v4.7.0 onwards, libvirt _explicitly_
        # declared the "preferred" default for x86 as 'pc' (and
        # appropriate values for other architectures), and only uses
        # QEMU's reported default (whatever that may be) if 'pc' does
        # not exist.  This was done "to isolate applications from
        # hypervisor changes that may cause incompatibilities" --
        # i.e. if, or when, QEMU changes its default machine type to
        # something else.  Refer to this libvirt commit:
        #
        #   https://libvirt.org/git/?p=libvirt.git;a=commit;h=26cfb1a3
        try:
            cap_obj = self._get_domain_capabilities(
                emulator_bin=emulator_bin, arch=arch,
                machine_type=machine_type, virt_type=virt_type)
        except libvirt.libvirtError as ex:
            # NOTE(sean-k-mooney): This can happen for several
            # reasons, but one common example is if you have
            # multiple QEMU emulators installed and you set
            # virt-type=kvm. In this case any non-native emulator,
            # e.g. AArch64 on an x86 host, will (correctly) raise
            # an exception as KVM cannot be used to accelerate CPU
            # instructions for non-native architectures.
            error_code = ex.get_error_code()
            LOG.debug(
                "Error from libvirt when retrieving domain capabilities "
                "for arch %(arch)s / virt_type %(virt_type)s / "
                "machine_type %(mach_type)s: "
                "[Error Code %(error_code)s]: %(exception)s",
                {'arch': arch, 'virt_type': virt_type,
                 'mach_type': machine_type, 'error_code': error_code,
                 'exception': ex})
            # Remove archs added by default dict lookup when checking
            # if the machine type has already been recoded.
            if arch in domain_caps:
                domain_caps.pop(arch)
            return

        # Register the domain caps using the expanded form of
        # machine type returned by libvirt in the <machine>
        # element (e.g. pc-i440fx-2.11)
        if cap_obj.machine_type:
            domain_caps[arch][cap_obj.machine_type] = cap_obj
        else:
            # NOTE(aspiers): In theory this should never happen,
            # but better safe than sorry.
            LOG.warning(
                "libvirt getDomainCapabilities("
                "emulator_bin=%(emulator_bin)s, arch=%(arch)s, "
                "machine_type=%(machine_type)s, virt_type=%(virt_type)s) "
                "returned null <machine> type",
                {'emulator_bin': emulator_bin, 'arch': arch,
                 'machine_type': machine_type, 'virt_type': virt_type}
            )

        # And if we passed an alias, register the domain caps
        # under that too.
        if machine_type and machine_type != cap_obj.machine_type:
            domain_caps[arch][machine_type] = cap_obj
            cap_obj.machine_type_alias = machine_type

    def _get_domain_capabilities(self, emulator_bin=None, arch=None,
                                 machine_type=None, virt_type=None, flags=0):
        xmlstr = self.get_connection().getDomainCapabilities(
            emulator_bin,
            arch,
            machine_type,
            virt_type,
            flags
        )
        LOG.debug("Libvirt host hypervisor capabilities for arch=%s and "
                  "machine_type=%s:\n%s", arch, machine_type, xmlstr)
        caps = vconfig.LibvirtConfigDomainCaps()
        caps.parse_str(xmlstr)
        return caps

    def get_driver_type(self):
        """Get hypervisor type.

        :returns: hypervisor type (ex. qemu)

        """

        return self.get_connection().getType()

    def get_version(self):
        """Get hypervisor version.

        :returns: hypervisor version (ex. 12003)

        """

        return self.get_connection().getVersion()

    def get_hostname(self):
        """Returns the hostname of the hypervisor."""
        hostname = self.get_connection().getHostname()
        if self._hostname is None:
            self._hostname = hostname
        elif hostname != self._hostname:
            LOG.error('Hostname has changed from %(old)s '
                      'to %(new)s. A restart is required to take effect.',
                      {'old': self._hostname, 'new': hostname})
        return self._hostname

    def find_secret(self, usage_type, usage_id):
        """Find a secret.

        usage_type: one of 'iscsi', 'ceph', 'rbd' or 'volume'
        usage_id: name of resource in secret
        """
        if usage_type == 'iscsi':
            usage_type_const = libvirt.VIR_SECRET_USAGE_TYPE_ISCSI
        elif usage_type in ('rbd', 'ceph'):
            usage_type_const = libvirt.VIR_SECRET_USAGE_TYPE_CEPH
        elif usage_type == 'volume':
            usage_type_const = libvirt.VIR_SECRET_USAGE_TYPE_VOLUME
        else:
            msg = _("Invalid usage_type: %s")
            raise exception.InternalError(msg % usage_type)

        try:
            conn = self.get_connection()
            return conn.secretLookupByUsage(usage_type_const, usage_id)
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_NO_SECRET:
                return None

    def create_secret(self, usage_type, usage_id, password=None):
        """Create a secret.

        :param usage_type: one of 'iscsi', 'ceph', 'rbd' or 'volume'
                           'rbd' will be converted to 'ceph'.
        :param usage_id: name of resource in secret
        :param password: optional secret value to set
        """
        secret_conf = vconfig.LibvirtConfigSecret()
        secret_conf.ephemeral = False
        secret_conf.private = False
        secret_conf.usage_id = usage_id
        if usage_type in ('rbd', 'ceph'):
            secret_conf.usage_type = 'ceph'
        elif usage_type == 'iscsi':
            secret_conf.usage_type = 'iscsi'
        elif usage_type == 'volume':
            secret_conf.usage_type = 'volume'
        else:
            msg = _("Invalid usage_type: %s")
            raise exception.InternalError(msg % usage_type)

        xml = secret_conf.to_xml()
        try:
            LOG.debug('Secret XML: %s', xml)
            conn = self.get_connection()
            secret = conn.secretDefineXML(xml)
            if password is not None:
                secret.setValue(password)
            return secret
        except libvirt.libvirtError:
            with excutils.save_and_reraise_exception():
                LOG.error('Error defining a secret with XML: %s', xml)

    def delete_secret(self, usage_type, usage_id):
        """Delete a secret.

        usage_type: one of 'iscsi', 'ceph', 'rbd' or 'volume'
        usage_id: name of resource in secret
        """
        secret = self.find_secret(usage_type, usage_id)
        if secret is not None:
            secret.undefine()

    def _get_hardware_info(self):
        """Returns hardware information about the Node.

        Note that the memory size is reported in MiB instead of KiB.
        """
        return self.get_connection().getInfo()

    def get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.

        :returns: the total amount of memory(MB).
        """
        if CONF.libvirt.file_backed_memory > 0:
            return CONF.libvirt.file_backed_memory
        else:
            return self._get_hardware_info()[1]

    def _sum_domain_memory_mb(self, include_host=True):
        """Get the total memory consumed by guest domains

        If include_host is True, subtract available host memory from guest 0
        to get real used memory within dom0 within xen
        """
        used = 0
        for guest in self.list_guests(only_guests=False):
            try:
                # TODO(sahid): Use get_info...
                dom_mem = int(guest._get_domain_info()[2])
            except libvirt.libvirtError as e:
                LOG.warning("couldn't obtain the memory from domain:"
                            " %(uuid)s, exception: %(ex)s",
                            {"uuid": guest.uuid, "ex": e})
                continue
            if include_host and guest.id == 0:
                # Memory usage for the host domain (dom0 in xen) is the
                # reported memory minus available memory
                used += (dom_mem - self._get_avail_memory_kb())
            else:
                used += dom_mem
        # Convert it to MB
        return used // units.Ki

    @staticmethod
    def _get_avail_memory_kb():
        with open('/proc/meminfo') as fp:
            m = fp.read().split()
        idx1 = m.index('MemFree:')
        idx2 = m.index('Buffers:')
        idx3 = m.index('Cached:')

        avail = int(m[idx1 + 1]) + int(m[idx2 + 1]) + int(m[idx3 + 1])

        return avail

    def get_memory_mb_used(self):
        """Get the used memory size(MB) of physical computer.

        :returns: the total usage of memory(MB).
        """
        if CONF.libvirt.virt_type == 'xen':
            # For xen, report the sum of all domains, with
            return self._sum_domain_memory_mb(include_host=True)
        elif CONF.libvirt.file_backed_memory > 0:
            # For file_backed_memory, report the total usage of guests,
            # ignoring host memory
            return self._sum_domain_memory_mb(include_host=False)
        else:
            return (self.get_memory_mb_total() -
                   (self._get_avail_memory_kb() // units.Ki))

    def get_cpu_stats(self):
        """Returns the current CPU state of the host with frequency."""
        stats = self.get_connection().getCPUStats(
            libvirt.VIR_NODE_CPU_STATS_ALL_CPUS, 0)
        # getInfo() returns various information about the host node
        # No. 3 is the expected CPU frequency.
        stats["frequency"] = self._get_hardware_info()[3]
        return stats

    def write_instance_config(self, xml):
        """Defines a domain, but does not start it.

        :param xml: XML domain definition of the guest.

        :returns: an instance of Guest
        """
        if six.PY2:
            xml = encodeutils.safe_encode(xml)
        domain = self.get_connection().defineXML(xml)
        return libvirt_guest.Guest(domain)

    def device_lookup_by_name(self, name):
        """Lookup a node device by its name.


        :returns: a virNodeDevice instance
        """
        return self.get_connection().nodeDeviceLookupByName(name)

    def list_pci_devices(self, flags=0):
        """Lookup pci devices.

        :returns: a list of virNodeDevice instance
        """
        return self._list_devices("pci", flags=flags)

    def list_mdev_capable_devices(self, flags=0):
        """Lookup devices supporting mdev capabilities.

        :returns: a list of virNodeDevice instance
        """
        return self._list_devices("mdev_types", flags=flags)

    def list_mediated_devices(self, flags=0):
        """Lookup mediated devices.

        :returns: a list of virNodeDevice instance
        """
        return self._list_devices("mdev", flags=flags)

    def _list_devices(self, cap, flags=0):
        """Lookup devices.

        :returns: a list of virNodeDevice instance
        """
        try:
            return self.get_connection().listDevices(cap, flags)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_SUPPORT:
                LOG.warning("URI %(uri)s does not support "
                            "listDevices: %(error)s",
                            {'uri': self._uri, 'error': ex})
                return []
            else:
                raise

    def compare_cpu(self, xmlDesc, flags=0):
        """Compares the given CPU description with the host CPU."""
        return self.get_connection().compareCPU(xmlDesc, flags)

    def is_cpu_control_policy_capable(self):
        """Returns whether kernel configuration CGROUP_SCHED is enabled

        CONFIG_CGROUP_SCHED may be disabled in some kernel configs to
        improve scheduler latency.
        """
        try:
            with open("/proc/self/mounts", "r") as fd:
                for line in fd.readlines():
                    # mount options and split options
                    bits = line.split()[3].split(",")
                    if "cpu" in bits:
                        return True
                return False
        except IOError:
            return False

    @property
    def has_hyperthreading(self):
        """Determine if host CPU has SMT, a.k.a. HyperThreading.

        :return: True if the host has SMT enabled, else False.
        """
        if self._has_hyperthreading is not None:
            return self._has_hyperthreading

        self._has_hyperthreading = False

        # we don't use '/capabilities/host/cpu/topology' since libvirt doesn't
        # guarantee the accuracy of this information
        for cell in self.get_capabilities().host.topology.cells:
            if any(len(cpu.siblings) > 1 for cpu in cell.cpus if cpu.siblings):
                self._has_hyperthreading = True
                break

        return self._has_hyperthreading

    def _kernel_supports_amd_sev(self):
        if not os.path.exists(SEV_KERNEL_PARAM_FILE):
            LOG.debug("%s does not exist", SEV_KERNEL_PARAM_FILE)
            return False

        with open(SEV_KERNEL_PARAM_FILE) as f:
            contents = f.read()
            LOG.debug("%s contains [%s]", SEV_KERNEL_PARAM_FILE, contents)
            return contents == "1\n"

    @property
    def supports_amd_sev(self):
        """Returns a boolean indicating whether AMD SEV (Secure Encrypted
        Virtualization) is supported.  This is conditional on support
        in the hardware, kernel, qemu, and libvirt.

        The result is memoized, since it is not expected to change
        during the lifetime of a running nova-compute service; if the
        hypervisor stack is changed or reconfigured in a way which
        would affect the support, nova-compute should be restarted
        anyway.
        """
        if self._supports_amd_sev is None:
            self._set_amd_sev_support()
        return self._supports_amd_sev

    def _set_amd_sev_support(self):
        self._supports_amd_sev = False

        if not self._kernel_supports_amd_sev():
            LOG.info("kernel doesn't support AMD SEV")
            self._supports_amd_sev = False
            return

        domain_caps = self.get_domain_capabilities()
        for arch in domain_caps:
            for machine_type in domain_caps[arch]:
                LOG.debug("Checking SEV support for arch %s "
                          "and machine type %s", arch, machine_type)
                for feature in domain_caps[arch][machine_type].features:
                    feature_is_sev = isinstance(
                        feature, vconfig.LibvirtConfigDomainCapsFeatureSev)
                    if (feature_is_sev and feature.supported):
                        LOG.info("AMD SEV support detected")
                        self._supports_amd_sev = True
                        return

        LOG.debug("No AMD SEV support detected for any (arch, machine_type)")
