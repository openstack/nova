# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
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
A connection to XenServer or Xen Cloud Platform.

The concurrency model for this class is as follows:

All XenAPI calls are on a thread (using t.i.t.deferToThread, via the decorator
deferredToThread).  They are remote calls, and so may hang for the usual
reasons.  They should not be allowed to block the reactor thread.

All long-running XenAPI calls (VM.start, VM.reboot, etc) are called async
(using XenAPI.VM.async_start etc).  These return a task, which can then be
polled for completion.  Polling is handled using reactor.callLater.

This combination of techniques means that we don't block the reactor thread at
all, and at the same time we don't hold lots of threads waiting for
long-running operations.

FIXME: get_info currently doesn't conform to these rules, and will block the
reactor thread if the VM.get_by_name_label or VM.get_record calls block.

**Related Flags**

:xenapi_connection_url:  URL for connection to XenServer/Xen Cloud Platform.
:xenapi_connection_username:  Username for connection to XenServer/Xen Cloud
                              Platform (default: root).
:xenapi_connection_password:  Password for connection to XenServer/Xen Cloud
                              Platform.
:xenapi_task_poll_interval:  The interval (seconds) used for polling of
                             remote tasks (Async.VM.start, etc)
                             (default: 0.5).

"""

import logging
import sys
import xmlrpclib

from eventlet import event
from eventlet import tpool

from nova import context
from nova import db
from nova import utils
from nova import flags
from nova.virt.xenapi.vmops import VMOps
from nova.virt.xenapi.volumeops import VolumeOps

FLAGS = flags.FLAGS
flags.DEFINE_string('xenapi_connection_url',
                    None,
                    'URL for connection to XenServer/Xen Cloud Platform.'
                    ' Required if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_username',
                    'root',
                    'Username for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_string('xenapi_connection_password',
                    None,
                    'Password for connection to XenServer/Xen Cloud Platform.'
                    ' Used only if connection_type=xenapi.')
flags.DEFINE_float('xenapi_task_poll_interval',
                   0.5,
                   'The interval used for polling of remote tasks '
                   '(Async.VM.start, etc).  Used only if '
                   'connection_type=xenapi.')

XenAPI = None


def get_connection(_):
    """Note that XenAPI doesn't have a read-only connection mode, so
    the read_only parameter is ignored."""
    # This is loaded late so that there's no need to install this
    # library when not using XenAPI.
    global XenAPI
    if XenAPI is None:
        XenAPI = __import__('XenAPI')
    url = FLAGS.xenapi_connection_url
    username = FLAGS.xenapi_connection_username
    password = FLAGS.xenapi_connection_password
    if not url or password is None:
        raise Exception(_('Must specify xenapi_connection_url, '
                          'xenapi_connection_username (optionally), and '
                          'xenapi_connection_password to use '
                          'connection_type=xenapi'))
    return XenAPIConnection(url, username, password)


class XenAPIConnection(object):
    """A connection to XenServer or Xen Cloud Platform"""

    def __init__(self, url, user, pw):
        session = XenAPISession(url, user, pw)
        self._vmops = VMOps(session)
        self._volumeops = VolumeOps(session)

    def list_instances(self):
        """List VM instances"""
        return self._vmops.list_instances()

    def spawn(self, instance):
        """Create VM instance"""
        self._vmops.spawn(instance)

    def reboot(self, instance):
        """Reboot VM instance"""
        self._vmops.reboot(instance)

    def destroy(self, instance):
        """Destroy VM instance"""
        self._vmops.destroy(instance)

    def pause(self, instance, callback):
        """Pause VM instance"""
        self._vmops.pause(instance, callback)

    def unpause(self, instance, callback):
        """Unpause paused VM instance"""
        self._vmops.unpause(instance, callback)

    def get_info(self, instance_id):
        """Return data about VM instance"""
        return self._vmops.get_info(instance_id)

    def get_diagnostics(self, instance_id):
        """Return data about VM diagnostics"""
        return self._vmops.get_diagnostics(instance_id)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        return self._vmops.get_console_output(instance)

    def attach_volume(self, instance_name, device_path, mountpoint):
        """Attach volume storage to VM instance"""
        return self._volumeops.attach_volume(instance_name,
                                               device_path,
                                               mountpoint)

    def detach_volume(self, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        return self._volumeops.detach_volume(instance_name, mountpoint)


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls"""

    def __init__(self, url, user, pw):
        self._session = XenAPI.Session(url)
        self._session.login_with_password(user, pw)

    def get_xenapi(self):
        """Return the xenapi object"""
        return self._session.xenapi

    def get_xenapi_host(self):
        """Return the xenapi host"""
        return self._session.xenapi.session.get_this_host(self._session.handle)

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread."""
        f = self._session.xenapi
        for m in method.split('.'):
            f = f.__getattr__(m)
        return tpool.execute(f, *args)

    def async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread."""
        return tpool.execute(_unwrap_plugin_exceptions,
                             self._session.xenapi.Async.host.call_plugin,
                             self.get_xenapi_host(), plugin, fn, args)

    def wait_for_task(self, instance_id, task):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes."""

        done = event.Event()
        loop = utils.LoopingCall(self._poll_task, instance_id, task, done)
        loop.start(FLAGS.xenapi_task_poll_interval, now=True)
        rv = done.wait()
        loop.stop()
        return rv

    def _poll_task(self, instance_id, task, done):
        """Poll the given XenAPI task, and fire the given Deferred if we
        get a result."""
        try:
            name = self._session.xenapi.task.get_name_label(task)
            status = self._session.xenapi.task.get_status(task)
            action = dict(
                instance_id=int(instance_id),
                action=name,
                error=None)
            if status == "pending":
                return
            elif status == "success":
                result = self._session.xenapi.task.get_result(task)
                logging.info(_("Task [%s] %s status: success    %s") % (
                    name,
                    task,
                    result))
                done.send(_parse_xmlrpc_value(result))
            else:
                error_info = self._session.xenapi.task.get_error_info(task)
                action["error"] = str(error_info)
                logging.warn(_("Task [%s] %s status: %s    %s") % (
                    name,
                    task,
                    status,
                    error_info))
                done.send_exception(XenAPI.Failure(error_info))
            db.instance_action_create(context.get_admin_context(), action)
        except XenAPI.Failure, exc:
            logging.warn(exc)
            done.send_exception(*sys.exc_info())


def _unwrap_plugin_exceptions(func, *args, **kwargs):
    """Parse exception details"""
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, exc:
        logging.debug(_("Got exception: %s"), exc)
        if (len(exc.details) == 4 and
            exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
            exc.details[2] == 'Failure'):
            params = None
            try:
                params = eval(exc.details[3])
            except:
                raise exc
            raise XenAPI.Failure(params)
        else:
            raise
    except xmlrpclib.ProtocolError, exc:
        logging.debug(_("Got exception: %s"), exc)
        raise


def _parse_xmlrpc_value(val):
    """Parse the given value as if it were an XML-RPC value.  This is
    sometimes used as the format for the task.result field."""
    if not val:
        return val
    x = xmlrpclib.loads(
        '<?xml version="1.0"?><methodResponse><params><param>' +
        val +
        '</param></params></methodResponse>')
    return x[0][0]
