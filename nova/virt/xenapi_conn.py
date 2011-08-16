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

**Variable Naming Scheme**

- suffix "_ref" for opaque references
- suffix "_uuid" for UUIDs
- suffix "_rec" for record objects
"""

import json
import random
import sys
import urlparse
import xmlrpclib

from eventlet import event
from eventlet import tpool
from eventlet import timeout

from nova import context
from nova import db
from nova import exception
from nova import utils
from nova import flags
from nova import log as logging
from nova.virt import driver
from nova.virt.xenapi import vm_utils
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
flags.DEFINE_integer('xenapi_vhd_coalesce_max_attempts',
                     5,
                     'Max number of times to poll for VHD to coalesce.'
                     '  Used only if connection_type=xenapi.')
flags.DEFINE_string('xenapi_agent_path',
                    'usr/sbin/xe-update-networking',
                    'Specifies the path in which the xenapi guest agent'
                    '  should be located. If the agent is present,'
                    '  network configuration is not injected into the image'
                    '  Used only if connection_type=xenapi.'
                    '  and flat_injected=True')
flags.DEFINE_string('xenapi_sr_base_path', '/var/run/sr-mount',
                    'Base path to the storage repository')
flags.DEFINE_string('target_host',
                    None,
                    'iSCSI Target Host')
flags.DEFINE_string('target_port',
                    '3260',
                    'iSCSI Target Port, 3260 Default')
flags.DEFINE_string('iqn_prefix',
                    'iqn.2010-10.org.openstack',
                    'IQN Prefix')
# NOTE(sirp): This is a work-around for a bug in Ubuntu Maverick, when we pull
# support for it, we should remove this
flags.DEFINE_bool('xenapi_remap_vbd_dev', False,
                  'Used to enable the remapping of VBD dev '
                  '(Works around an issue in Ubuntu Maverick)')
flags.DEFINE_string('xenapi_remap_vbd_dev_prefix', 'sd',
                    'Specify prefix to remap VBD dev to '
                    '(ex. /dev/xvdb -> /dev/sdb)')
flags.DEFINE_integer('xenapi_login_timeout',
                     10,
                     'Timeout in seconds for XenAPI login.')


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


class XenAPIConnection(driver.ComputeDriver):
    """A connection to XenServer or Xen Cloud Platform"""

    def __init__(self, url, user, pw):
        super(XenAPIConnection, self).__init__()
        self._session = XenAPISession(url, user, pw)
        self._vmops = VMOps(self._session)
        self._volumeops = VolumeOps(self._session)
        self._host_state = None

    @property
    def HostState(self):
        if not self._host_state:
            self._host_state = HostState(self._session)
        return self._host_state

    def init_host(self, host):
        #FIXME(armando): implement this
        #NOTE(armando): would we need a method
        #to call when shutting down the host?
        #e.g. to do session logout?
        pass

    def list_instances(self):
        """List VM instances"""
        return self._vmops.list_instances()

    def list_instances_detail(self):
        return self._vmops.list_instances_detail()

    def spawn(self, context, instance,
              network_info=None, block_device_info=None):
        """Create VM instance"""
        self._vmops.spawn(context, instance, network_info)

    def revert_migration(self, instance):
        """Reverts a resize, powering back on the instance"""
        self._vmops.revert_migration(instance)

    def finish_migration(self, context, instance, disk_info, network_info,
                         resize_instance=False):
        """Completes a resize, turning on the migrated instance"""
        self._vmops.finish_migration(context, instance, disk_info,
                                     network_info, resize_instance)

    def snapshot(self, context, instance, image_id):
        """ Create snapshot from a running VM instance """
        self._vmops.snapshot(context, instance, image_id)

    def reboot(self, instance, network_info):
        """Reboot VM instance"""
        self._vmops.reboot(instance)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance"""
        self._vmops.set_admin_password(instance, new_pass)

    def inject_file(self, instance, b64_path, b64_contents):
        """Create a file on the VM instance. The file path and contents
        should be base64-encoded.
        """
        self._vmops.inject_file(instance, b64_path, b64_contents)

    def destroy(self, instance, network_info, cleanup=True):
        """Destroy VM instance"""
        self._vmops.destroy(instance, network_info)

    def pause(self, instance, callback):
        """Pause VM instance"""
        self._vmops.pause(instance, callback)

    def unpause(self, instance, callback):
        """Unpause paused VM instance"""
        self._vmops.unpause(instance, callback)

    def migrate_disk_and_power_off(self, instance, dest):
        """Transfers the VHD of a running instance to another host, then shuts
        off the instance copies over the COW disk"""
        return self._vmops.migrate_disk_and_power_off(instance, dest)

    def suspend(self, instance, callback):
        """suspend the specified instance"""
        self._vmops.suspend(instance, callback)

    def resume(self, instance, callback):
        """resume the specified instance"""
        self._vmops.resume(instance, callback)

    def rescue(self, context, instance, _callback, network_info):
        """Rescue the specified instance"""
        self._vmops.rescue(context, instance, _callback, network_info)

    def unrescue(self, instance, _callback, network_info):
        """Unrescue the specified instance"""
        self._vmops.unrescue(instance, _callback)

    def poll_rescued_instances(self, timeout):
        """Poll for rescued instances"""
        self._vmops.poll_rescued_instances(timeout)

    def reset_network(self, instance):
        """reset networking for specified instance"""
        self._vmops.reset_network(instance)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance"""
        self._vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance_ref, network_info):
        self._vmops.plug_vifs(instance_ref, network_info)

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

    def get_host_ip_addr(self):
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return xs_url.netloc

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

    def update_available_resource(self, ctxt, host):
        """This method is supported only by libvirt."""
        return

    def compare_cpu(self, xml):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        """This method is supported only libvirt."""
        return

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """This method is supported only by libvirt."""
        return

    def unfilter_instance(self, instance_ref, network_info):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def update_host_status(self):
        """Update the status info of the host, and return those values
            to the calling program."""
        return self.HostState.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
        return self.HostState.get_host_stats(refresh=refresh)

    def host_power_action(self, host, action):
        """The only valid values for 'action' on XenServer are 'reboot' or
        'shutdown', even though the API also accepts 'startup'. As this is
        not technically possible on XenServer, since the host is the same
        physical machine as the hypervisor, if this is requested, we need to
        raise an exception.
        """
        if action in ("reboot", "shutdown"):
            return self._vmops.host_power_action(host, action)
        else:
            msg = _("Host startup on XenServer is not supported.")
            raise NotImplementedError(msg)

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        return self._vmops.set_host_enabled(host, enabled)


class XenAPISession(object):
    """The session to invoke XenAPI SDK calls"""

    def __init__(self, url, user, pw):
        self.XenAPI = self.get_imported_xenapi()
        self._session = self._create_session(url)
        exception = self.XenAPI.Failure(_("Unable to log in to XenAPI "
                            "(is the Dom0 disk full?)"))
        with timeout.Timeout(FLAGS.xenapi_login_timeout, exception):
            self._session.login_with_password(user, pw)

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

    def wait_for_task(self, task, id=None):
        """Return the result of the given task. The task is polled
        until it completes."""
        done = event.Event()
        loop = utils.LoopingCall(f=None)

        def _poll_task():
            """Poll the given XenAPI task, and return the result if the
            action was completed successfully or not.
            """
            try:
                name = self._session.xenapi.task.get_name_label(task)
                status = self._session.xenapi.task.get_status(task)
                # Ensure action is never > 255
                action = dict(action=name[:255], error=None)
                if id:
                    action["instance_id"] = int(id)
                if status == "pending":
                    return
                elif status == "success":
                    result = self._session.xenapi.task.get_result(task)
                    LOG.info(_("Task [%(name)s] %(task)s status:"
                            " success    %(result)s") % locals())
                    done.send(_parse_xmlrpc_value(result))
                else:
                    error_info = self._session.xenapi.task.get_error_info(task)
                    action["error"] = str(error_info)
                    LOG.warn(_("Task [%(name)s] %(task)s status:"
                            " %(status)s    %(error_info)s") % locals())
                    done.send_exception(self.XenAPI.Failure(error_info))

                if id:
                    db.instance_action_create(context.get_admin_context(),
                            action)
            except self.XenAPI.Failure, exc:
                LOG.warn(exc)
                done.send_exception(*sys.exc_info())
            loop.stop()

        loop.f = _poll_task
        loop.start(FLAGS.xenapi_task_poll_interval, now=True)
        return done.wait()

    def _create_session(self, url):
        """Stubout point. This can be replaced with a mock session."""
        return self.XenAPI.Session(url)

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
                except Exception:
                    raise exc
                raise self.XenAPI.Failure(params)
            else:
                raise
        except xmlrpclib.ProtocolError, exc:
            LOG.debug(_("Got exception: %s"), exc)
            raise


class HostState(object):
    """Manages information about the XenServer host this compute
    node is running on.
    """
    def __init__(self, session):
        super(HostState, self).__init__()
        self._session = session
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh:
            self.update_status()
        return self._stats

    def update_status(self):
        """Since under Xenserver, a compute node runs on a given host,
        we can get host status information using xenapi.
        """
        LOG.debug(_("Updating host stats"))
        # Make it something unlikely to match any actual instance ID
        task_id = random.randint(-80000, -70000)
        task = self._session.async_call_plugin("xenhost", "host_data", {})
        task_result = self._session.wait_for_task(task, task_id)
        if not task_result:
            task_result = json.dumps("")
        try:
            data = json.loads(task_result)
        except ValueError as e:
            # Invalid JSON object
            LOG.error(_("Unable to get updated status: %s") % e)
            return
        # Get the SR usage
        try:
            sr_ref = vm_utils.safe_find_sr(self._session)
        except exception.NotFound as e:
            # No SR configured
            LOG.error(_("Unable to get SR for this host: %s") % e)
            return
        sr_rec = self._session.get_xenapi().SR.get_record(sr_ref)
        total = int(sr_rec["virtual_allocation"])
        used = int(sr_rec["physical_utilisation"])
        data["disk_total"] = total
        data["disk_used"] = used
        data["disk_available"] = total - used
        host_memory = data.get('host_memory', None)
        if host_memory:
            data["host_memory_total"] = host_memory.get('total', 0)
            data["host_memory_overhead"] = host_memory.get('overhead', 0)
            data["host_memory_free"] = host_memory.get('free', 0)
            data["host_memory_free_computed"] = \
                        host_memory.get('free-computed', 0)
            del data['host_memory']
        self._stats = data


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
