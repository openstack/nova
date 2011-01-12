# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright 2010 OpenStack LLC.
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

All XenAPI calls are on a green thread (using eventlet's "tpool"
thread pool). They are remote calls, and so may hang for the usual
reasons.

All long-running XenAPI calls (VM.start, VM.reboot, etc) are called async
(using XenAPI.VM.async_start etc). These return a task, which can then be
polled for completion.

This combination of techniques means that we don't block the main thread at
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
:target_host:                the iSCSI Target Host IP address, i.e. the IP
                             address for the nova-volume host
:target_port:                iSCSI Target Port, 3260 Default
:iqn_prefix:                 IQN Prefix, e.g. 'iqn.2010-10.org.openstack'
"""

import sys
import urlparse
import xmlrpclib

from eventlet import event
from eventlet import tpool

from nova import context
from nova import db
from nova import utils
from nova import flags
from nova import log as logging
from nova.virt.xenapi.vmops import VMOps
from nova.virt.xenapi.volumeops import VolumeOps


LOG = logging.getLogger("nova.virt.xenapi")


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
                   '(Async.VM.start, etc). Used only if '
                   'connection_type=xenapi.')
flags.DEFINE_float('xenapi_vhd_coalesce_poll_interval',
                   5.0,
                   'The interval used for polling of coalescing vhds.'
                   '  Used only if connection_type=xenapi.')
flags.DEFINE_string('target_host',
                    None,
                    'iSCSI Target Host')
flags.DEFINE_string('target_port',
                    '3260',
                    'iSCSI Target Port, 3260 Default')
flags.DEFINE_string('iqn_prefix',
                    'iqn.2010-10.org.openstack',
                    'IQN Prefix')


def get_connection(_):
    """Note that XenAPI doesn't have a read-only connection mode, so
    the read_only parameter is ignored."""
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

    def init_host(self):
        #FIXME(armando): implement this
        #NOTE(armando): would we need a method
        #to call when shutting down the host?
        #e.g. to do session logout?
        pass

    def list_instances(self):
        """List VM instances"""
        return self._vmops.list_instances()

    def spawn(self, instance):
        """Create VM instance"""
        self._vmops.spawn(instance)

    def snapshot(self, instance, name):
        """ Create snapshot from a running VM instance """
        self._vmops.snapshot(instance, name)

    def reboot(self, instance):
        """Reboot VM instance"""
        self._vmops.reboot(instance)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance"""
        self._vmops.set_admin_password(instance, new_pass)

    def destroy(self, instance):
        """Destroy VM instance"""
        self._vmops.destroy(instance)

    def pause(self, instance, callback):
        """Pause VM instance"""
        self._vmops.pause(instance, callback)

    def unpause(self, instance, callback):
        """Unpause paused VM instance"""
        self._vmops.unpause(instance, callback)

    def suspend(self, instance, callback):
        """suspend the specified instance"""
        self._vmops.suspend(instance, callback)

    def resume(self, instance, callback):
        """resume the specified instance"""
        self._vmops.resume(instance, callback)

    def get_info(self, instance_id):
        """Return data about VM instance"""
        return self._vmops.get_info(instance_id)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        return self._vmops.get_diagnostics(instance)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        return self._vmops.get_console_output(instance)

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console"""
        return self._vmops.get_ajax_console(instance)

    def attach_volume(self, instance_name, device_path, mountpoint):
        """Attach volume storage to VM instance"""
        return self._volumeops.attach_volume(instance_name,
                                               device_path,
                                               mountpoint)

    def detach_volume(self, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        return self._volumeops.detach_volume(instance_name, mountpoint)

    def get_console_pool_info(self, console_type):
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return  {'address': xs_url.netloc,
                 'username': FLAGS.xenapi_connection_username,
                 'password': FLAGS.xenapi_connection_password}


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls"""

    def __init__(self, url, user, pw):
        self.XenAPI = self.get_imported_xenapi()
        self._session = self._create_session(url)
        self._session.login_with_password(user, pw)
        self.loop = None

    def get_imported_xenapi(self):
        """Stubout point. This can be replaced with a mock xenapi module."""
        return __import__('XenAPI')

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

    def call_xenapi_request(self, method, *args):
        """Some interactions with dom0, such as interacting with xenstore's
        param record, require using the xenapi_request method of the session
        object. This wraps that call on a background thread.
        """
        f = self._session.xenapi_request
        return tpool.execute(f, method, *args)

    def async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread."""
        return tpool.execute(self._unwrap_plugin_exceptions,
                             self._session.xenapi.Async.host.call_plugin,
                             self.get_xenapi_host(), plugin, fn, args)

    def wait_for_task(self, id, task):
        """Return the result of the given task. The task is polled
        until it completes. Not re-entrant."""
        done = event.Event()
        self.loop = utils.LoopingCall(self._poll_task, id, task, done)
        self.loop.start(FLAGS.xenapi_task_poll_interval, now=True)
        rv = done.wait()
        self.loop.stop()
        return rv

    def _stop_loop(self):
        """Stop polling for task to finish."""
        #NOTE(sandy-walsh) Had to break this call out to support unit tests.
        if self.loop:
            self.loop.stop()

    def _create_session(self, url):
        """Stubout point. This can be replaced with a mock session."""
        return self.XenAPI.Session(url)

    def _poll_task(self, id, task, done):
        """Poll the given XenAPI task, and fire the given action if we
        get a result.
        """
        try:
            name = self._session.xenapi.task.get_name_label(task)
            status = self._session.xenapi.task.get_status(task)
            action = dict(
                instance_id=int(id),
                action=name[0:255],  # Ensure action is never > 255
                error=None)
            if status == "pending":
                return
            elif status == "success":
                result = self._session.xenapi.task.get_result(task)
                LOG.info(_("Task [%s] %s status: success    %s") % (
                    name,
                    task,
                    result))
                done.send(_parse_xmlrpc_value(result))
            else:
                error_info = self._session.xenapi.task.get_error_info(task)
                action["error"] = str(error_info)
                LOG.warn(_("Task [%s] %s status: %s    %s") % (
                    name,
                    task,
                    status,
                    error_info))
                done.send_exception(self.XenAPI.Failure(error_info))
            db.instance_action_create(context.get_admin_context(), action)
        except self.XenAPI.Failure, exc:
            LOG.warn(exc)
            done.send_exception(*sys.exc_info())
        self._stop_loop()

    def _unwrap_plugin_exceptions(self, func, *args, **kwargs):
        """Parse exception details"""
        try:
            return func(*args, **kwargs)
        except self.XenAPI.Failure, exc:
            LOG.debug(_("Got exception: %s"), exc)
            if (len(exc.details) == 4 and
                exc.details[0] == 'XENAPI_PLUGIN_EXCEPTION' and
                exc.details[2] == 'Failure'):
                params = None
                try:
                    params = eval(exc.details[3])
                except:
                    raise exc
                raise self.XenAPI.Failure(params)
            else:
                raise
        except xmlrpclib.ProtocolError, exc:
            LOG.debug(_("Got exception: %s"), exc)
            raise


def _parse_xmlrpc_value(val):
    """Parse the given value as if it were an XML-RPC value. This is
    sometimes used as the format for the task.result field."""
    if not val:
        return val
    x = xmlrpclib.loads(
        '<?xml version="1.0"?><methodResponse><params><param>' +
        val +
        '</param></params></methodResponse>')
    return x[0][0]
