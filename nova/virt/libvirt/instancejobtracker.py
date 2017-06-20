# Copyright 2015 NTT corp.
# All Rights Reserved.
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


import collections
import errno
import os
import signal

from oslo_log import log as logging


LOG = logging.getLogger(__name__)


class InstanceJobTracker(object):
    def __init__(self):
        self.jobs = collections.defaultdict(list)

    def add_job(self, instance, pid):
        """Appends process_id of instance to cache.

        This method will store the pid of a process in cache as
        a key: value pair which will be used to kill the process if it
        is running while deleting the instance. Instance uuid is used as
        a key in the cache and pid will be the value.

        :param instance: Object of instance
        :param pid: Id of the process
        """
        self.jobs[instance.uuid].append(pid)

    def remove_job(self, instance, pid):
        """Removes pid of process from cache.

        This method will remove the pid of a process from the cache.

        :param instance: Object of instance
        :param pid: Id of the process
        """
        uuid = instance.uuid
        if uuid in self.jobs and pid in self.jobs[uuid]:
            self.jobs[uuid].remove(pid)

        # remove instance.uuid if no pid's remaining
        if not self.jobs[uuid]:
            self.jobs.pop(uuid, None)

    def terminate_jobs(self, instance):
        """Kills the running processes for given instance.

        This method is used to kill all running processes of the instance if
        it is deleted in between.

        :param instance: Object of instance
        """
        pids_to_remove = list(self.jobs.get(instance.uuid, []))
        for pid in pids_to_remove:
            try:
                # Try to kill the process
                os.kill(pid, signal.SIGKILL)
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    LOG.error('Failed to kill process %(pid)s '
                              'due to %(reason)s, while deleting the '
                              'instance.', {'pid': pid, 'reason': exc},
                              instance=instance)

            try:
                # Check if the process is still alive.
                os.kill(pid, 0)
            except OSError as exc:
                if exc.errno != errno.ESRCH:
                    LOG.error('Unexpected error while checking process '
                              '%(pid)s.', {'pid': pid}, instance=instance)
            else:
                # The process is still around
                LOG.warning("Failed to kill a long running process "
                            "%(pid)s related to the instance when "
                            "deleting it.", {'pid': pid}, instance=instance)

            self.remove_job(instance, pid)
