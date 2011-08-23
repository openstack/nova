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
Utility classes for defining the time saving transfer of data from the reader
to the write using a LightQueue as a Pipe between the reader and the writer.
"""

from eventlet import event
from eventlet import greenthread
from eventlet.queue import LightQueue

from glance import client

from nova import exception
from nova import log as logging

LOG = logging.getLogger("nova.virt.vmwareapi.io_util")

IO_THREAD_SLEEP_TIME = .01
GLANCE_POLL_INTERVAL = 5


class ThreadSafePipe(LightQueue):
    """The pipe to hold the data which the reader writes to and the writer
    reads from."""

    def __init__(self, maxsize, transfer_size):
        LightQueue.__init__(self, maxsize)
        self.transfer_size = transfer_size
        self.transferred = 0

    def read(self, chunk_size):
        """Read data from the pipe. Chunksize if ignored for we have ensured
        that the data chunks written to the pipe by readers is the same as the
        chunks asked for by the Writer."""
        if self.transferred < self.transfer_size:
            data_item = self.get()
            self.transferred += len(data_item)
            return data_item
        else:
            return ""

    def write(self, data):
        """Put a data item in the pipe."""
        self.put(data)

    def close(self):
        """A place-holder to maintain consistency."""
        pass


class GlanceWriteThread(object):
    """Ensures that image data is written to in the glance client and that
    it is in correct ('active')state."""

    def __init__(self, input, glance_client, image_id, image_meta=None):
        if not image_meta:
            image_meta = {}

        self.input = input
        self.glance_client = glance_client
        self.image_id = image_id
        self.image_meta = image_meta
        self._running = False

    def start(self):
        self.done = event.Event()

        def _inner():
            """Function to do the image data transfer through an update
            and thereon checks if the state is 'active'."""
            self.glance_client.update_image(self.image_id,
                                            image_meta=self.image_meta,
                                            image_data=self.input)
            self._running = True
            while self._running:
                try:
                    image_status = \
                        self.glance_client.get_image_meta(self.image_id).get(
                                                                "status")
                    if image_status == "active":
                        self.stop()
                        self.done.send(True)
                    # If the state is killed, then raise an exception.
                    elif image_status == "killed":
                        self.stop()
                        exc_msg = _("Glance image %s is in killed state") %\
                                    self.image_id
                        LOG.exception(exc_msg)
                        self.done.send_exception(exception.Error(exc_msg))
                    elif image_status in ["saving", "queued"]:
                        greenthread.sleep(GLANCE_POLL_INTERVAL)
                    else:
                        self.stop()
                        exc_msg = _("Glance image "
                                    "%(image_id)s is in unknown state "
                                    "- %(state)s") % {
                                            "image_id": self.image_id,
                                            "state": image_status}
                        LOG.exception(exc_msg)
                        self.done.send_exception(exception.Error(exc_msg))
                except Exception, exc:
                    self.stop()
                    self.done.send_exception(exc)

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()

    def close(self):
        pass


class IOThread(object):
    """Class that reads chunks from the input file and writes them to the
    output file till the transfer is completely done."""

    def __init__(self, input, output):
        self.input = input
        self.output = output
        self._running = False
        self.got_exception = False

    def start(self):
        self.done = event.Event()

        def _inner():
            """Read data from the input and write the same to the output
            until the transfer completes."""
            self._running = True
            while self._running:
                try:
                    data = self.input.read(None)
                    if not data:
                        self.stop()
                        self.done.send(True)
                    self.output.write(data)
                    greenthread.sleep(IO_THREAD_SLEEP_TIME)
                except Exception, exc:
                    self.stop()
                    LOG.exception(exc)
                    self.done.send_exception(exc)

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()
