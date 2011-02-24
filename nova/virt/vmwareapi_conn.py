# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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
Connection class for VMware Infrastructure API in VMware ESX/ESXi platform

Encapsulates the session management activties and acts as interface for VI API.
The connection class sets up a session with the ESX/ESXi compute provider host
and handles all the calls made to the host.

**Related Flags**

:vmwareapi_host_ip: IP of VMware ESX/ESXi compute provider host
:vmwareapi_host_username: ESX/ESXi server user to be used for API session
:vmwareapi_host_password: Password for the user "vmwareapi_host_username"
:vmwareapi_task_poll_interval: The interval used for polling of remote tasks
:vmwareapi_api_retry_count: Max number of retry attempts upon API failures

"""

import logging
import time
import urlparse

from eventlet import event

from nova import context
from nova import db
from nova import flags
from nova import utils

from nova.virt.vmwareapi import vim
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi.vmops import VMWareVMOps

LOG = logging.getLogger("nova.virt.vmwareapi_conn")

FLAGS = flags.FLAGS
flags.DEFINE_string('vmwareapi_host_ip',
                    None,
                    'URL for connection to VMWare ESX host.'
                    'Required if connection_type is vmwareapi.')
flags.DEFINE_string('vmwareapi_host_username',
                    None,
                    'Username for connection to VMWare ESX host.'
                    'Used only if connection_type is vmwareapi.')
flags.DEFINE_string('vmwareapi_host_password',
                    None,
                    'Password for connection to VMWare ESX host.'
                    'Used only if connection_type is vmwareapi.')
flags.DEFINE_float('vmwareapi_task_poll_interval',
                   1.0,
                   'The interval used for polling of remote tasks '
                   'Used only if connection_type is vmwareapi')
flags.DEFINE_float('vmwareapi_api_retry_count',
                   10,
                   'The number of times we retry on failures, '
                   'e.g., socket error, etc.'
                   'Used only if connection_type is vmwareapi')

TIME_BETWEEN_API_CALL_RETRIES = 2.0


class TaskState:
    """Enumeration class for different states of task
    0 - Task completed successfully
    1 - Task is in queued state
    2 - Task is in running state
    """

    TASK_SUCCESS = 0
    TASK_QUEUED = 1
    TASK_RUNNING = 2


class Failure(Exception):
    """Base Exception class for handling task failures"""

    def __init__(self, details):
        """Initializer"""
        self.details = details

    def __str__(self):
        """The informal string representation of the object"""
        return str(self.details)


def get_connection(_):
    """Sets up the ESX host connection"""
    host_ip = FLAGS.vmwareapi_host_ip
    host_username = FLAGS.vmwareapi_host_username
    host_password = FLAGS.vmwareapi_host_password
    api_retry_count = FLAGS.vmwareapi_api_retry_count
    if not host_ip  or host_username is None or host_password is None:
        raise Exception('Must specify vmwareapi_host_ip,'
                        'vmwareapi_host_username '
                        'and vmwareapi_host_password to use'
                        'connection_type=vmwareapi')
    return VMWareESXConnection(host_ip, host_username, host_password,
                               api_retry_count)


class VMWareESXConnection(object):
    """The ESX host connection object"""

    def __init__(self, host_ip, host_username, host_password,
                 api_retry_count, scheme="https"):
        """The Initializer"""
        session = VMWareAPISession(host_ip, host_username, host_password,
                 api_retry_count, scheme=scheme)
        self._vmops = VMWareVMOps(session)

    def init_host(self, host):
        """Do the initialization that needs to be done"""
        #FIXME(sateesh): implement this
        pass

    def list_instances(self):
        """List VM instances"""
        return self._vmops.list_instances()

    def spawn(self, instance):
        """Create VM instance"""
        self._vmops.spawn(instance)

    def snapshot(self, instance, name):
        """Create snapshot from a running VM instance"""
        self._vmops.snapshot(instance, name)

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

    def suspend(self, instance, callback):
        """Suspend the specified instance"""
        self._vmops.suspend(instance, callback)

    def resume(self, instance, callback):
        """Resume the suspended VM instance"""
        self._vmops.resume(instance, callback)

    def get_info(self, instance_id):
        """Return info about the VM instance"""
        return self._vmops.get_info(instance_id)

    def get_diagnostics(self, instance):
        """Return data about VM diagnostics"""
        return self._vmops.get_info(instance)

    def get_console_output(self, instance):
        """Return snapshot of console"""
        return self._vmops.get_console_output(instance)

    def get_ajax_console(self, instance):
        """Return link to instance's ajax console"""
        return self._vmops.get_ajax_console(instance)

    def attach_volume(self, instance_name, device_path, mountpoint):
        """Attach volume storage to VM instance"""
        pass

    def detach_volume(self, instance_name, mountpoint):
        """Detach volume storage to VM instance"""
        pass

    def get_console_pool_info(self, console_type):
        """Get info about the host on which the VM resides"""
        esx_url = urlparse.urlparse(FLAGS.vmwareapi_host_ip)
        return  {'address': esx_url.netloc,
                 'username': FLAGS.vmwareapi_host_password,
                 'password': FLAGS.vmwareapi_host_password}

    def _create_dummy_vm_for_test(self, instance):
        """Creates a dummy VM with default parameters for testing purpose"""
        return self._vmops._create_dummy_vm_for_test(instance)


class VMWareAPISession(object):
    """Sets up a session with ESX host and handles all calls made to host"""

    def __init__(self, host_ip, host_username, host_password,
                 api_retry_count, scheme="https"):
        """Set the connection credentials"""
        self._host_ip = host_ip
        self._host_username = host_username
        self._host_password = host_password
        self.api_retry_count = api_retry_count
        self._scheme = scheme
        self._session_id = None
        self.vim = None
        self._create_session()

    def _create_session(self):
        """Creates a session with the ESX host"""
        while True:
            try:
                # Login and setup the session with the ESX host for making
                # API calls
                self.vim = vim.Vim(protocol=self._scheme, host=self._host_ip)
                session = self.vim.Login(
                               self.vim.get_service_content().SessionManager,
                               userName=self._host_username,
                               password=self._host_password)
                # Terminate the earlier session, if possible ( For the sake of
                # preserving sessions as there is a limit to the number of
                # sessions we can have )
                if self._session_id:
                    try:
                        self.vim.TerminateSession(
                                self.vim.get_service_content().SessionManager,
                                sessionId=[self._session_id])
                    except Exception, excep:
                        LOG.exception(excep)
                self._session_id = session.Key
                return
            except Exception, excep:
                LOG.info(_("In vmwareapi:_create_session, "
                              "got this exception: %s") % excep)
                raise Exception(excep)

    def __del__(self):
        """The Destructor. Logs-out the session."""
        # Logout to avoid un-necessary increase in session count at the
        # ESX host
        try:
            self.vim.Logout(self.vim.get_service_content().SessionManager)
        except Exception:
            pass

    def _call_method(self, module, method, *args, **kwargs):
        """Calls a method within the module specified with args provided"""
        args = list(args)
        retry_count = 0
        exc = None
        while True:
            try:
                if not isinstance(module, vim.Vim):
                    #If it is not the first try, then get the latest vim object
                    if retry_count > 0:
                        args = args[1:]
                    args = [self.vim] + args
                retry_count += 1
                temp_module = module

                for method_elem in method.split("."):
                    temp_module = getattr(temp_module, method_elem)

                ret_val = temp_module(*args, **kwargs)
                return ret_val
            except vim.SessionFaultyException, excep:
                # If it is a Session Fault Exception, it may point
                # to a session gone bad. So we try re-creating a session
                # and then proceeding ahead with the call.
                exc = excep
                self._create_session()
            except vim.SessionOverLoadException, excep:
                # For exceptions which may come because of session overload,
                # we retry
                exc = excep
            except Exception, excep:
                # If it is a proper exception, say not having furnished
                # proper data in the SOAP call or the retry limit having
                # exceeded, we raise the exception
                exc = excep
                break
            # If retry count has been reached then break and
            # raise the exception
            if retry_count > self.api_retry_count:
                break
            time.sleep(TIME_BETWEEN_API_CALL_RETRIES)

        LOG.info(_("In vmwareapi:_call_method, "
                     "got this exception: ") % exc)
        raise Exception(exc)

    def _get_vim(self):
        """Gets the VIM object reference"""
        if self.vim is None:
            self._create_session()
        return self.vim

    def _wait_for_task(self, instance_id, task_ref):
        """
        Return a Deferred that will give the result of the given task.
        The task is polled until it completes.
        """
        done = event.Event()
        self.loop = utils.LoopingCall(self._poll_task, instance_id, task_ref,
                                      done)
        self.loop.start(FLAGS.vmwareapi_task_poll_interval, now=True)
        ret_val = done.wait()
        self.loop.stop()
        return ret_val

    def _poll_task(self, instance_id, task_ref, done):
        """
        Poll the given task, and fires the given Deferred if we
        get a result.
        """
        try:
            task_info = self._call_method(vim_util, "get_dynamic_property",
                            task_ref, "Task", "info")
            task_name = task_info.Name
            action = dict(
                instance_id=int(instance_id),
                action=task_name[0:255],
                error=None)
            if task_info.State in [TaskState.TASK_QUEUED,
                                   TaskState.TASK_RUNNING]:
                return
            elif task_info.State == TaskState.TASK_SUCCESS:
                LOG.info(_("Task [%(taskname)s] %(taskref)s status: success") %
                         {'taskname': task_name,
                          'taskref': str(task_ref)})
                done.send(TaskState.TASK_SUCCESS)
            else:
                error_info = str(task_info.Error.LocalizedMessage)
                action["error"] = error_info
                LOG.info(_("Task [%(task_name)s] %(task_ref)s status: "
                         "error [%(error_info)s]") %
                         {'task_name': task_name,
                          'task_ref': str(task_ref),
                          'error_info': error_info})
                done.send_exception(Exception(error_info))
            db.instance_action_create(context.get_admin_context(), action)
        except Exception, excep:
            LOG.info(_("In vmwareapi:_poll_task, Got this error %s") % excep)
            done.send_exception(excep)
