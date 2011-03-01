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
Reads a chunk from input file and writes the same to the output file till
it reaches the transferable size
"""

from Queue import Empty
from Queue import Full
from Queue import Queue
from threading import Thread
import time
import traceback

THREAD_SLEEP_TIME = 0.01


class ThreadSafePipe(Queue):
    """ThreadSafePipe class queues the chunk data"""

    def __init__(self, max_size=None):
        Queue.__init__(self, max_size)
        self.eof = False

    def write(self, data):
        """Writes the chunk data to the queue"""
        self.put(data, block=False)

    def read(self):
        """Retrieves the chunk data from the queue"""
        return self.get(block=False)

    def set_eof(self, eof):
        """Sets EOF to mark reading of input file finishes"""
        self.eof = eof

    def get_eof(self):
        """Returns whether EOF reached."""
        return self.eof


class IOThread(Thread):
    """IOThread reads chunks from input file and pipes it to output file till
    it reaches the transferable size
    """

    def __init__(self, input_file, output_file, chunk_size, transfer_size):
        Thread.__init__(self)
        self.input_file = input_file
        self.output_file = output_file
        self.chunk_size = chunk_size
        self.transfer_size = transfer_size
        self.read_size = 0
        self._done = False
        self._stop_transfer = False
        self._error = False
        self._exception = None

    def run(self):
        """Pipes the input chunk read to the output file till it reaches
        a transferable size
        """
        try:
            if self.transfer_size and self.transfer_size <= self.chunk_size:
                self.chunk_size = self.transfer_size
            data = None
            while True:
                if not self.transfer_size is None:
                    if self.read_size >= self.transfer_size:
                        break
                if self._stop_transfer:
                    break
                try:
                    #read chunk only if no previous chunk
                    if data is None:
                        if isinstance(self.input_file, ThreadSafePipe):
                            data = self.input_file.read()
                        else:
                            data = self.input_file.read(self.chunk_size)
                            if not data:
                                # no more data to read
                                break
                    if data:
                        # write chunk
                        self.output_file.write(data)
                        self.read_size = self.read_size + len(data)
                        # clear chunk since write is a success
                        data = None
                except Empty:
                    # Pipe side is empty - safe to check for eof signal
                    if self.input_file.get_eof():
                        # no more data in read
                        break
                    #Restrict tight loop
                    time.sleep(THREAD_SLEEP_TIME)
                except Full:
                    # Pipe full while writing to pipe - safe to retry since
                    #chunk is preserved
                    #Restrict tight loop
                    time.sleep(THREAD_SLEEP_TIME)
            if isinstance(self.output_file, ThreadSafePipe):
                # If this is the reader thread, send eof signal
                self.output_file.set_eof(True)

            if not self.transfer_size is None:
                if self.read_size < self.transfer_size:
                    raise IOError(_("Not enough data (%(read_size)d "
                                    "of %(transfer_size)d bytes)") \
                                    % ({'read_size': self.read_size,
                                        'transfer_size': self.transfer_size}))

        except Exception:
            self._error = True
            self._exception = str(traceback.format_exc())
        self._done = True

    def stop_io_transfer(self):
        """Set the stop flag to true, which causes the thread to stop
        safely
        """
        self._stop_transfer = True
        self.join()

    def get_error(self):
        """Returns the error string"""
        return self._error

    def get_exception(self):
        """Returns the traceback exception string"""
        return self._exception

    def is_done(self):
        """Checks whether transfer is complete"""
        return self._done
