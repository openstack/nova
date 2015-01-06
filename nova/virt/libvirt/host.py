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

import os
import socket
import threading

import eventlet
from eventlet import greenio
from eventlet import greenthread
from eventlet import patcher
from eventlet import tpool

from nova import exception
from nova.i18n import _
from nova.i18n import _LW
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import event as virtevent

libvirt = None

LOG = logging.getLogger(__name__)

native_socket = patcher.original('socket')
native_threading = patcher.original("threading")
native_Queue = patcher.original("Queue")


class Host(object):

    def __init__(self, uri, read_only=False,
                 conn_event_handler=None,
                 lifecycle_event_handler=None):

        global libvirt
        if libvirt is None:
            libvirt = __import__('libvirt')

        self._uri = uri
        self._read_only = read_only
        self._conn_event_handler = conn_event_handler
        self._lifecycle_event_handler = lifecycle_event_handler

        self._wrapped_conn = None
        self._wrapped_conn_lock = threading.Lock()
        self._event_queue = None

        self._events_delayed = {}
        # Note(toabctl): During a reboot of a Xen domain, STOPPED and
        #                STARTED events are sent. To prevent shutting
        #                down the domain during a reboot, delay the
        #                STOPPED lifecycle event some seconds.
        if uri.find("xen://") != -1:
            self._lifecycle_delay = 15
        else:
            self._lifecycle_delay = 0

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
        raise exception.NovaException(
            _("Can not handle authentication request for %d credentials")
            % len(creds))

    @staticmethod
    def _connect(uri, read_only):
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
        # tpool.proxy_call creates a native thread. Due to limitations
        # with eventlet locking we cannot use the logging API inside
        # the called function.
        return tpool.proxy_call(
            (libvirt.virDomain, libvirt.virConnect),
            libvirt.openAuth, uri, auth, flags)

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
                    self._event_delayed_cleanup(event)
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
                if self._conn_event_handler is not None:
                    self._conn_event_handler(False, msg)

    def _event_delayed_cleanup(self, event):
        """Cleanup possible delayed stop events."""
        if (event.transition == virtevent.EVENT_LIFECYCLE_STARTED or
            event.transition == virtevent.EVENT_LIFECYCLE_RESUMED):
            if event.uuid in self._events_delayed.keys():
                self._events_delayed[event.uuid].cancel()
                self._events_delayed.pop(event.uuid, None)
                LOG.debug("Removed pending event for %s due to "
                          "lifecycle event", event.uuid)

    def _event_emit_delayed(self, event):
        """Emit events - possibly delayed."""
        def event_cleanup(gt, *args, **kwargs):
            """Callback function for greenthread. Called
            to cleanup the _events_delayed dictionary when a event
            was called.
            """
            event = args[0]
            self._events_delayed.pop(event.uuid, None)

        if self._lifecycle_delay > 0:
            if event.uuid not in self._events_delayed.keys():
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
        eventlet.spawn(self._dispatch_thread)

    def _get_new_connection(self):
        # call with _wrapped_conn_lock held
        LOG.debug('Connecting to libvirt: %s', self._uri)
        wrapped_conn = None

        try:
            wrapped_conn = self._connect(self._uri, self._read_only)
        finally:
            # Enabling the compute service, in case it was disabled
            # since the connection was successful.
            disable_reason = None
            if not wrapped_conn:
                disable_reason = 'Failed to connect to libvirt'

            if self._conn_event_handler is not None:
                self._conn_event_handler(bool(wrapped_conn), disable_reason)

        self._wrapped_conn = wrapped_conn

        try:
            LOG.debug("Registering for lifecycle events %s", self)
            wrapped_conn.domainEventRegisterAny(
                None,
                libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                self._event_lifecycle_callback,
                self)
        except Exception as e:
            LOG.warn(_LW("URI %(uri)s does not support events: %(error)s"),
                     {'uri': self._uri, 'error': e})

        try:
            LOG.debug("Registering for connection events: %s", str(self))
            wrapped_conn.registerCloseCallback(self._close_callback, None)
        except (TypeError, AttributeError) as e:
            # NOTE: The registerCloseCallback of python-libvirt 1.0.1+
            # is defined with 3 arguments, and the above registerClose-
            # Callback succeeds. However, the one of python-libvirt 1.0.0
            # is defined with 4 arguments and TypeError happens here.
            # Then python-libvirt 0.9 does not define a method register-
            # CloseCallback.
            LOG.debug("The version of python-libvirt does not support "
                      "registerCloseCallback or is too old: %s", e)
        except libvirt.libvirtError as e:
            LOG.warn(_LW("URI %(uri)s does not support connection"
                         " events: %(error)s"),
                     {'uri': self._uri, 'error': e})

        return wrapped_conn

    def get_connection(self):
        # multiple concurrent connections are protected by _wrapped_conn_lock
        with self._wrapped_conn_lock:
            wrapped_conn = self._wrapped_conn
            if not wrapped_conn or not self._test_connection(wrapped_conn):
                wrapped_conn = self._get_new_connection()

        return wrapped_conn

    @staticmethod
    def _libvirt_error_handler(context, err):
        # Just ignore instead of default outputting to stderr.
        pass

    def initialize(self):
        # NOTE(dkliban): Error handler needs to be registered before libvirt
        #                connection is used for the first time.  Otherwise, the
        #                handler does not get registered.
        libvirt.registerErrorHandler(self._libvirt_error_handler, None)
        libvirt.virEventRegisterDefaultImpl()
        self._init_events()

    def has_min_version(self, lv_ver=None, hv_ver=None, hv_type=None):
        conn = self.get_connection()
        try:
            if lv_ver is not None:
                libvirt_version = conn.getLibVersion()

                if libvirt_version < utils.convert_version_to_int(lv_ver):
                    return False

            if hv_ver is not None:
                hypervisor_version = conn.getVersion()
                if hypervisor_version < utils.convert_version_to_int(hv_ver):
                    return False

            if hv_type is not None:
                hypervisor_type = conn.getType()
                if hypervisor_type != hv_type:
                    return False

            return True
        except Exception:
            return False
