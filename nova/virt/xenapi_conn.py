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
import xmlrpclib

from twisted.internet import defer
from twisted.internet import reactor

from nova import utils

from xenapi.vmops import VMOps
from xenapi.volumeops import VolumeOps
from xenapi.novadeps import Configuration

XenAPI = None
Config = Configuration()


def get_connection(_):
    """Note that XenAPI doesn't have a read-only connection mode, so
    the read_only parameter is ignored."""
    # This is loaded late so that there's no need to install this
    # library when not using XenAPI.
    global XenAPI
    if XenAPI is None:
        XenAPI = __import__('XenAPI')
    url = Config.xenapi_connection_url
    username = Config.xenapi_connection_username
    password = Config.xenapi_connection_password
    if not url or password is None:
        raise Exception('Must specify xenapi_connection_url, '
                        'xenapi_connection_username (optionally), and '
                        'xenapi_connection_password to use '
                        'connection_type=xenapi')
    return XenAPIConnection(url, username, password)


class XenAPIConnection(object):
    """ A connection to XenServer or Xen Cloud Platform """
    def __init__(self, url, user, pw):
        session = XenAPISession(url, user, pw)
        self._vmops = VMOps(session)
        self._volumeops = VolumeOps(session)

    def list_instances(self):
        """ List VM instances """
        return self._vmops.list_instances()

    def spawn(self, instance):
        """ Create VM instance """
        self._vmops.spawn(instance)

    def reboot(self, instance):
        """ Reboot VM instance """
        self._vmops.reboot(instance)

    def destroy(self, instance):
        """ Destroy VM instance """
        self._vmops.destroy(instance)

    def get_info(self, instance_id):
        """ Return data about VM instance """
        return self._vmops.get_info(instance_id)

    def get_console_output(self, instance):
        """ Return snapshot of console """
        return self._vmops.get_console_output(instance)

    def attach_volume(self, instance_name, device_path, mountpoint):
        """ Attach volume storage to VM instance """
        return self._volumeops.attach_volume(instance_name,
                                               device_path,
                                               mountpoint)

    def detach_volume(self, instance_name, mountpoint):
        """ Detach volume storage to VM instance """
        return self._volumeops.detach_volume(instance_name, mountpoint)


class XenAPISession(object):
    """ The session to invoke XenAPI SDK calls """
    def __init__(self, url, user, pw):
        self._session = XenAPI.Session(url)
        self._session.login_with_password(user, pw)

    def get_xenapi(self):
        """ Return the xenapi object """
        return self._session.xenapi

    def get_xenapi_host(self):
        """ Return the xenapi host """
        return self._session.xenapi.session.get_this_host(self._session.handle)

    @utils.deferredToThread
    def call_xenapi(self, method, *args):
        """Call the specified XenAPI method on a background thread.  Returns
        a Deferred for the result."""
        f = self._session.xenapi
        for m in method.split('.'):
            f = f.__getattr__(m)
        return f(*args)

    @utils.deferredToThread
    def async_call_plugin(self, plugin, fn, args):
        """Call Async.host.call_plugin on a background thread.  Returns a
        Deferred with the task reference."""
        return _unwrap_plugin_exceptions(
            self._session.xenapi.Async.host.call_plugin,
            self.get_xenapi_host(), plugin, fn, args)

    def wait_for_task(self, task):
        """Return a Deferred that will give the result of the given task.
        The task is polled until it completes."""
        d = defer.Deferred()
        reactor.callLater(0, self._poll_task, task, d)
        return d

    @utils.deferredToThread
    def _poll_task(self, task, deferred):
        """Poll the given XenAPI task, and fire the given Deferred if we
        get a result."""
        try:
            #logging.debug('Polling task %s...', task)
            status = self._session.xenapi.task.get_status(task)
            if status == 'pending':
                reactor.callLater(Config.xenapi_task_poll_interval,
                                  self._poll_task, task, deferred)
            elif status == 'success':
                result = self._session.xenapi.task.get_result(task)
                logging.info('Task %s status: success.  %s', task, result)
                deferred.callback(_parse_xmlrpc_value(result))
            else:
                error_info = self._session.xenapi.task.get_error_info(task)
                logging.warn('Task %s status: %s.  %s', task, status,
                             error_info)
                deferred.errback(XenAPI.Failure(error_info))
            #logging.debug('Polling task %s done.', task)
        except XenAPI.Failure, exc:
            logging.warn(exc)
            deferred.errback(exc)


def _unwrap_plugin_exceptions(func, *args, **kwargs):
    """ Parse exception details """
    try:
        return func(*args, **kwargs)
    except XenAPI.Failure, exc:
        logging.debug("Got exception: %s", exc)
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
        logging.debug("Got exception: %s", exc)
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
