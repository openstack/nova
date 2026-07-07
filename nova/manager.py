# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""Base Manager class.

Managers are responsible for a certain aspect of the system.  It is a logical
grouping of code relating to a portion of the system.  In general other
components should be using the manager to make changes to the components that
it is responsible for.

For example, other components that need to deal with volumes in some way,
should do so by calling methods on the VolumeManager instead of directly
changing fields in the database.  This allows us to keep all of the code
relating to volumes in the same place.

We have adopted a basic strategy of Smart managers and dumb data, which means
rather than attaching methods to data objects, components should call manager
methods that act on the data.

Methods on managers that can be executed locally should be called directly. If
a particular method must execute on a remote host, this should be done via rpc
to the service that wraps the manager

Managers should be responsible for most of the db access, and
non-implementation specific data.  Anything implementation specific that can't
be generalized should be done by the Driver.

In general, we prefer to have one manager with multiple drivers for different
implementations, but sometimes it makes sense to have multiple managers.  You
can think of it this way: Abstract different overall strategies at the manager
level(FlatNetwork vs VlanNetwork), and different implementations at the driver
level(LinuxNetDriver vs CiscoNetDriver).

Managers will often provide methods for initial setup of a host or periodic
tasks to a wrapping service.

This module provides Manager, a base class for managers.

"""

import threading
import time

from oslo_log import log as logging
from oslo_service import periodic_task

import nova.conf
import nova.db.main.api
from nova import profiler
from nova import rpc


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def skip_automatic_rpc_tracking(func):
    """Mark a manager method to skip the RPC general wrapper tracking.

    To shutdown service gracefully, we need to track the RPC methods so
    that manager can wait and log them until those are completed. Not all
    the RPC methods will be tracked as part of RPC general wrapper tracking.
    A few examples of such methods are long-running tasks in the background,
    tasks which are ok to be interrupted during shutdown. This decorator will
    be used to skip such method to be tracked by the general tracking wrapper.
    """
    func._skip_automatic_rpc_tracking = True
    return func


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class ManagerMeta(profiler.get_traced_meta(), type(PeriodicTasks)):
    """Metaclass to trace all children of a specific class.

    This metaclass wraps every public method (not starting with _ or __)
    of the class using it. All children classes of the class using ManagerMeta
    will be profiled as well.

    Adding this metaclass requires that the __trace_args__ attribute be added
    to the class we want to modify. That attribute is a dictionary
    with one mandatory key: "name". "name" defines the name
    of the action to be traced (for example, wsgi, rpc, db).

    The OSprofiler-based tracing, although, will only happen if profiler
    instance was initiated somewhere before in the thread, that can only happen
    if profiling is enabled in nova.conf and the API call to Nova API contained
    specific headers.
    """


class Manager(PeriodicTasks, metaclass=ManagerMeta):
    __trace_args__ = {"name": "rpc"}

    def __init__(self, host=None, service_name='undefined'):
        if not host:
            host = CONF.host
        self.host = host
        self.backdoor_port = None
        self.service_name = service_name
        self.notifier = rpc.get_notifier(self.service_name, self.host)
        self.additional_endpoints = []
        self._shutdown_in_progress = threading.Event()
        self._in_progress_tasks = {}
        self._failed_tasks = {}
        self._completed_task_count = 0
        self._in_progress_task_key_counter = 0
        self._in_progress_task_cond = threading.Condition()
        super(Manager, self).__init__()

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        if self._shutdown_in_progress.is_set():
            LOG.debug('Skipping periodic tasks during graceful shutdown.')
            return
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

    def init_host(self, service_ref):
        """Hook to do additional manager initialization when one requests
        the service be started.  This is called before any service record
        is created, but if one already exists for this service, it is
        provided.

        Child classes should override this method.

        :param service_ref: An objects.Service if one exists, else None.
        """
        pass

    def set_shutdown_in_progress(self):
        self._shutdown_in_progress.set()

    def graceful_shutdown(self, timeout):
        """Hook to gracefully shutdown the manager.

        Child classes should override this method.
        """

        pass

    def cleanup_host(self):
        """Hook to do cleanup work when the service shuts down.

        Child classes should override this method.
        """
        pass

    def pre_start_hook(self, service_ref):
        """Hook to provide the manager the ability to do additional
        start-up work before any RPC queues/consumers are created. This is
        called after other initialization has succeeded and a service
        record is created.

        Child classes should override this method.

        :param service_ref: The nova.objects.Service for this
        """
        pass

    def post_start_hook(self):
        """Hook to provide the manager the ability to do additional
        start-up work immediately after a service creates RPC consumers
        and starts 'running'.

        Child classes should override this method.
        """
        pass

    def reset(self):
        """Hook called on SIGHUP to signal the manager to re-read any
        dynamic configuration or do any reconfiguration tasks.
        """
        pass

    def _record_task_start(
            self, task_name, instance_uuid=None, request_id=None):
        """Record the task when it is started.

        Records the task name, instance UUID, start_time, and request ID
        so they can be logged during shutdown.

        :param task_name: task name, most of time it is RPC method name.
        :param instance_uuid: Instance UUID if task is associated with
                              instance.
        :param request_id: request-id of the RPC call.
        :returns: task unique key.
        """
        with self._in_progress_task_cond:
            self._in_progress_task_key_counter += 1
            key = self._in_progress_task_key_counter
            start_time = time.monotonic()
            self._in_progress_tasks[key] = {
                'name': task_name,
                'instance_uuid': instance_uuid,
                'request_id': request_id,
                'start_time': start_time,
            }
        if self._shutdown_in_progress.is_set():
            LOG.info(
                'Graceful shutdown: new task started after shutdown '
                'initiated: %s (instance: %s, request_id: %s, '
                'start_time: %s)',
                task_name, instance_uuid, request_id, start_time)
        return key

    def _record_task_end(self, key, future=None, failed=False):
        """Remove task from task tracking dict.

        Log the completion of task only if shutdown is initiated so that we
        can know what all tasks finished during shutdown.

        This method is used as callback for future.add_done_callback() which
        calls the callback function with the completed future. When called
        as callback, task completion results is determined from the future

        :param key: Task unique key.
        :param future: The completed ``Future``, if this is used as a
            future.add_done_callback() callback. Task is considered failed
            when the future was cancelled or raised an exception (means not
            completed successfully).
        :param failed: Whether the task failed and record task end as failed
            task.
        """
        if future is not None:
            # NOTE(gmaan): Tasks end are recorded for logging so if it is
            # canceled or failed (means not completed successfully) then
            # record as failed task.
            failed = future.cancelled() or future.exception() is not None
        with self._in_progress_task_cond:
            task = self._in_progress_tasks.pop(key, None)
            if task is None:
                LOG.warning(
                    'Graceful shutdown: _record_task_end called for '
                    'unrecorded or already-ended task key: %s', key)
                return
            if self._shutdown_in_progress.is_set():
                if failed:
                    self._failed_tasks[key] = task
                else:
                    self._completed_task_count += 1
            remaining_count = len(self._in_progress_tasks)
            if self._shutdown_in_progress.is_set():
                elapsed = time.monotonic() - task['start_time']
                LOG.info(
                    'Graceful shutdown: task %s: %s '
                    '(instance: %s, request_id: %s, elapsed: %s, '
                    'remaining in-progress tasks: %d)',
                    'failed' if failed else 'completed',
                    task['name'], task['instance_uuid'], task['request_id'],
                    elapsed, remaining_count)
            if not self._in_progress_tasks:
                self._in_progress_task_cond.notify_all()

    def _summarize_in_progress_tasks(self):
        return ', '.join(
            '%s(instance=%s, request_id=%s, elapsed=%s)' % (
                t['name'], t['instance_uuid'], t['request_id'],
                time.monotonic() - t['start_time'])
            for t in self._in_progress_tasks.values())

    def _summarize_failed_tasks(self):
        return ', '.join(
            '%s(instance=%s, request_id=%s)' % (
                t['name'], t['instance_uuid'], t['request_id'])
            for t in self._failed_tasks.values())

    def _wait_for_in_progress_tasks(self, timeout):
        """Wait for all in-progress tasks to complete.

        Wait until all tasks are finished or timeout.

        :param timeout: Maximum number of seconds to wait.
        """
        log_interval = 10
        deadline = time.monotonic() + timeout

        with self._in_progress_task_cond:
            if not self._in_progress_tasks:
                LOG.info(
                    'Graceful shutdown: no in-progress tasks.')
                return

            LOG.info(
                'Graceful shutdown initiated with %d in-progress tasks: %s',
                len(self._in_progress_tasks),
                self._summarize_in_progress_tasks())

            while self._in_progress_tasks:
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    LOG.warning(
                        'Graceful shutdown timed out with %d tasks still '
                        'in progress: %s (completed tasks: %d, failed '
                        'tasks: %d%s)',
                        len(self._in_progress_tasks),
                        self._summarize_in_progress_tasks(),
                        self._completed_task_count, len(self._failed_tasks),
                        ': %s' % self._summarize_failed_tasks()
                        if self._failed_tasks else '')
                    return
                self._in_progress_task_cond.wait(
                    timeout=min(remaining_time, log_interval))
                if self._in_progress_tasks:
                    LOG.info(
                        'Graceful shutdown still waiting for %d in progress '
                        'tasks: %s',
                        len(self._in_progress_tasks),
                        self._summarize_in_progress_tasks())

        LOG.info(
            'Graceful shutdown: all in-progress tasks finished. '
            'completed tasks: %d, failed tasks: %d%s',
            self._completed_task_count, len(self._failed_tasks),
            ': %s' % self._summarize_failed_tasks()
            if self._failed_tasks else '')
