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

import contextlib
import json
import random
import sys
import time
import urlparse
import xmlrpclib

from eventlet import event
from eventlet import queue
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
flags.DEFINE_integer('xenapi_connection_concurrent',
                     5,
                     'Maximum number of concurrent XenAPI connections.'
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
flags.DEFINE_bool('xenapi_log_instance_actions', False,
                  'Log all instance calls to XenAPI in the database.')
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
        self._volumeops = VolumeOps(self._session)
        self._host_state = None
        self._product_version = self._session.get_product_version()
        self._vmops = VMOps(self._session, self._product_version)

    @property
    def host_state(self):
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

    def spawn(self, context, instance, image_meta,
              network_info=None, block_device_info=None):
        """Create VM instance"""
        self._vmops.spawn(context, instance, image_meta, network_info)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM"""
        # TODO(Vek): Need to pass context in for access to auth_token
        self._vmops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, instance):
        """Finish reverting a resize, powering back on the instance"""
        self._vmops.finish_revert_migration(instance)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False):
        """Completes a resize, turning on the migrated instance"""
        self._vmops.finish_migration(context, migration, instance, disk_info,
                                     network_info, image_meta, resize_instance)

    def snapshot(self, context, instance, image_id):
        """ Create snapshot from a running VM instance """
        self._vmops.snapshot(context, instance, image_id)

    def reboot(self, instance, network_info, reboot_type):
        """Reboot VM instance"""
        self._vmops.reboot(instance, reboot_type)

    def set_admin_password(self, instance, new_pass):
        """Set the root/admin password on the VM instance"""
        self._vmops.set_admin_password(instance, new_pass)

    def inject_file(self, instance, b64_path, b64_contents):
        """Create a file on the VM instance. The file path and contents
        should be base64-encoded.
        """
        self._vmops.inject_file(instance, b64_path, b64_contents)

    def destroy(self, instance, network_info, block_device_info=None):
        """Destroy VM instance"""
        self._vmops.destroy(instance, network_info)

    def pause(self, instance):
        """Pause VM instance"""
        self._vmops.pause(instance)

    def unpause(self, instance):
        """Unpause paused VM instance"""
        self._vmops.unpause(instance)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type):
        """Transfers the VHD of a running instance to another host, then shuts
        off the instance copies over the COW disk"""
        return self._vmops.migrate_disk_and_power_off(context, instance,
                                                      dest, instance_type)

    def suspend(self, instance):
        """suspend the specified instance"""
        self._vmops.suspend(instance)

    def resume(self, instance):
        """resume the specified instance"""
        self._vmops.resume(instance)

    def rescue(self, context, instance, network_info, image_meta):
        """Rescue the specified instance"""
        self._vmops.rescue(context, instance, network_info, image_meta)

    def unrescue(self, instance, network_info):
        """Unrescue the specified instance"""
        self._vmops.unrescue(instance)

    def power_off(self, instance):
        """Power off the specified instance"""
        self._vmops.power_off(instance)

    def power_on(self, instance):
        """Power on the specified instance"""
        self._vmops.power_on(instance)

    def poll_rebooting_instances(self, timeout):
        """Poll for rebooting instances"""
        self._vmops.poll_rebooting_instances(timeout)

    def poll_rescued_instances(self, timeout):
        """Poll for rescued instances"""
        self._vmops.poll_rescued_instances(timeout)

    def poll_unconfirmed_resizes(self, resize_confirm_window):
        """Poll for unconfirmed resizes"""
        self._vmops.poll_unconfirmed_resizes(resize_confirm_window)

    def reset_network(self, instance):
        """reset networking for specified instance"""
        self._vmops.reset_network(instance)

    def inject_network_info(self, instance, network_info):
        """inject network info for specified instance"""
        self._vmops.inject_network_info(instance, network_info)

    def plug_vifs(self, instance_ref, network_info):
        """Plug VIFs into networks."""
        self._vmops.plug_vifs(instance_ref, network_info)

    def unplug_vifs(self, instance_ref, network_info):
        """Unplug VIFs from networks."""
        self._vmops.unplug_vifs(instance_ref, network_info)

    def get_info(self, instance_name):
        """Return data about VM instance"""
        return self._vmops.get_info(instance_name)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        return self._vmops.get_diagnostics(instance)

    def get_all_bw_usage(self, start_time, stop_time=None):
        """Return bandwidth usage info for each interface on each
           running VM"""
        bwusage = []
        start_time = time.mktime(start_time.timetuple())
        if stop_time:
            stop_time = time.mktime(stop_time.timetuple())
        for iusage in self._vmops.get_all_bw_usage(start_time, stop_time).\
                      values():
            for macaddr, usage in iusage.iteritems():
                vi = db.virtual_interface_get_by_address(
                                    context.get_admin_context(),
                                    macaddr)
                if vi:
                    bwusage.append(dict(virtual_interface=vi,
                                        bw_in=usage['bw_in'],
                                        bw_out=usage['bw_out']))
        return bwusage

    def get_console_output(self, instance):
        """Return snapshot of console"""
        return self._vmops.get_console_output(instance)

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console"""
        return self._vmops.get_ajax_console(instance)

    @staticmethod
    def get_host_ip_addr():
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return xs_url.netloc

    def attach_volume(self, connection_info, instance_name, mountpoint):
        """Attach volume storage to VM instance"""
        return self._volumeops.attach_volume(connection_info,
                                             instance_name,
                                             mountpoint)

    def detach_volume(self, connection_info, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        return self._volumeops.detach_volume(connection_info,
                                             instance_name,
                                             mountpoint)

    def get_console_pool_info(self, console_type):
        xs_url = urlparse.urlparse(FLAGS.xenapi_connection_url)
        return  {'address': xs_url.netloc,
                 'username': FLAGS.xenapi_connection_username,
                 'password': FLAGS.xenapi_connection_password}

    def update_available_resource(self, ctxt, host):
        """Updates compute manager resource info on ComputeNode table.

        This method is called when nova-compute launches, and
        whenever admin executes "nova-manage service update_resource".

        :param ctxt: security context
        :param host: hostname that compute manager is currently running

        """

        try:
            service_ref = db.service_get_all_compute_by_host(ctxt, host)[0]
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=host)

        host_stats = self.get_host_stats(refresh=True)

        # Updating host information
        total_ram_mb = host_stats['host_memory_total'] / (1024 * 1024)
        free_ram_mb = host_stats['host_memory_free'] / (1024 * 1024)
        total_disk_gb = host_stats['disk_total'] / (1024 * 1024 * 1024)
        used_disk_gb = host_stats['disk_used'] / (1024 * 1024 * 1024)

        dic = {'vcpus': 0,
               'memory_mb': total_ram_mb,
               'local_gb': total_disk_gb,
               'vcpus_used': 0,
               'memory_mb_used': total_ram_mb - free_ram_mb,
               'local_gb_used': used_disk_gb,
               'hypervisor_type': 'xen',
               'hypervisor_version': 0,
               'cpu_info': host_stats['host_cpu_info']['cpu_count']}

        compute_node_ref = service_ref['compute_node']
        if not compute_node_ref:
            LOG.info(_('Compute_service record created for %s ') % host)
            dic['service_id'] = service_ref['id']
            db.compute_node_create(ctxt, dic)
        else:
            LOG.info(_('Compute_service record updated for %s ') % host)
            db.compute_node_update(ctxt, compute_node_ref[0]['id'], dic)

    def compare_cpu(self, xml):
        """This method is supported only by libvirt."""
        raise NotImplementedError('This method is supported only by libvirt.')

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        """This method is supported only libvirt."""
        # NOTE(salvatore-orlando): it enforces security groups on
        # host initialization and live migration.
        # Live migration is not supported by XenAPI (as of 2011-11-09)
        # In XenAPI we do not assume instances running upon host initialization
        return

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False):
        """This method is supported only by libvirt."""
        return

    def unfilter_instance(self, instance_ref, network_info):
        """Removes security groups configured for an instance."""
        return self._vmops.unfilter_instance(instance_ref, network_info)

    def refresh_security_group_rules(self, security_group_id):
        """ Updates security group rules for all instances
            associated with a given security group
            Invoked when security group rules are updated
        """
        return self._vmops.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        """ Updates security group rules for all instances
            associated with a given security group
            Invoked when instances are added/removed to a security group
        """
        return self._vmops.refresh_security_group_members(security_group_id)

    def update_host_status(self):
        """Update the status info of the host, and return those values
            to the calling program."""
        return self.host_state.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
        return self.host_state.get_host_stats(refresh=refresh)

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
        self._sessions = queue.Queue()
        exception = self.XenAPI.Failure(_("Unable to log in to XenAPI "
                            "(is the Dom0 disk full?)"))
        for i in xrange(FLAGS.xenapi_connection_concurrent):
            session = self._create_session(url)
            with timeout.Timeout(FLAGS.xenapi_login_timeout, exception):
                session.login_with_password(user, pw)
            self._sessions.put(session)

    def get_product_version(self):
        """Return a tuple of (major, minor, rev) for the host version"""
        host = self.get_xenapi_host()
        software_version = self.call_xenapi('host.get_software_version',
                                            host)
        product_version = software_version['product_version']
        return tuple(int(part) for part in product_version.split('.'))

    def get_imported_xenapi(self):
        """Stubout point. This can be replaced with a mock xenapi module."""
        return __import__('XenAPI')

    @contextlib.contextmanager
    def _get_session(self):
        """Return exclusive session for scope of with statement"""
        session = self._sessions.get()
        try:
            yield session
        finally:
            self._sessions.put(session)

    def get_xenapi_host(self):
        """Return the xenapi host"""
        with self._get_session() as session:
            return session.xenapi.session.get_this_host(session.handle)

    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread."""
        with self._get_session() as session:
            f = session.xenapi
            for m in method.split('.'):
                f = getattr(f, m)
            return tpool.execute(f, *args)

    def call_xenapi_request(self, method, *args):
        """Some interactions with dom0, such as interacting with xenstore's
        param record, require using the xenapi_request method of the session
        object. This wraps that call on a background thread.
        """
        with self._get_session() as session:
            f = session.xenapi_request
            return tpool.execute(f, method, *args)

    def async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread."""
        with self._get_session() as session:
            return tpool.execute(self._unwrap_plugin_exceptions,
                                 session.xenapi.Async.host.call_plugin,
                                 self.get_xenapi_host(), plugin, fn, args)

    def wait_for_task(self, task, uuid=None):
        """Return the result of the given task. The task is polled
        until it completes."""
        done = event.Event()
        loop = utils.LoopingCall(f=None)

        def _poll_task():
            """Poll the given XenAPI task, and return the result if the
            action was completed successfully or not.
            """
            try:
                ctxt = context.get_admin_context()
                name = self.call_xenapi("task.get_name_label", task)
                status = self.call_xenapi("task.get_status", task)

                # Ensure action is never > 255
                action = dict(action=name[:255], error=None)
                log_instance_actions = (FLAGS.xenapi_log_instance_actions and
                                        uuid)
                if log_instance_actions:
                    action["instance_uuid"] = uuid

                if status == "pending":
                    return
                elif status == "success":
                    result = self.call_xenapi("task.get_result", task)
                    LOG.info(_("Task [%(name)s] %(task)s status:"
                            " success    %(result)s") % locals())

                    if log_instance_actions:
                        db.instance_action_create(ctxt, action)

                    done.send(_parse_xmlrpc_value(result))
                else:
                    error_info = self.call_xenapi("task.get_error_info", task)
                    LOG.warn(_("Task [%(name)s] %(task)s status:"
                            " %(status)s    %(error_info)s") % locals())

                    if log_instance_actions:
                        action["error"] = str(error_info)
                        db.instance_action_create(ctxt, action)

                    done.send_exception(self.XenAPI.Failure(error_info))
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
        # Make it something unlikely to match any actual instance UUID
        task_id = random.randint(-80000, -70000)
        task = self._session.async_call_plugin("xenhost", "host_data", {})
        task_result = self._session.wait_for_task(task, str(task_id))
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
            sr_ref = vm_utils.VMHelper.safe_find_sr(self._session)
        except exception.NotFound as e:
            # No SR configured
            LOG.error(_("Unable to get SR for this host: %s") % e)
            return
        sr_rec = self._session.call_xenapi("SR.get_record", sr_ref)
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
