# Copyright 2014 Cloudbase Solutions Srl
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

import errno
import os

from eventlet import patcher

from nova.i18n import _LE
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

native_threading = patcher.original('threading')


class IOThread(native_threading.Thread):
    def __init__(self, src, dest, max_bytes):
        super(IOThread, self).__init__()
        self.setDaemon(True)
        self._src = src
        self._dest = dest
        self._dest_archive = dest + '.1'
        self._max_bytes = max_bytes
        self._stopped = native_threading.Event()

    def run(self):
        try:
            self._copy(self._src, self._dest)
        except IOError as err:
            # Invalid argument error means that the vm console pipe was closed,
            # probably the vm was stopped. The worker can stop it's execution.
            if err.errno != errno.EINVAL:
                LOG.error(_LE("Error writing vm console log file from "
                              "serial console pipe. Error: %s") % err)

    def _copy(self, src, dest):
        with open(self._src, 'rb') as src:
            with open(self._dest, 'ab', 0) as dest:
                dest.seek(0, os.SEEK_END)
                log_size = dest.tell()
                while (not self._stopped.isSet()):
                    # Read one byte at a time to avoid blocking.
                    data = src.read(1)
                    dest.write(data)
                    log_size += len(data)
                    if (log_size >= self._max_bytes):
                        dest.close()
                        if os.path.exists(self._dest_archive):
                            os.remove(self._dest_archive)
                        os.rename(self._dest, self._dest_archive)
                        dest = open(self._dest, 'ab', 0)
                        log_size = 0

    def join(self):
        self._stopped.set()
        super(IOThread, self).join()
