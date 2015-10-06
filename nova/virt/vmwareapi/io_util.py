# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
from eventlet import queue
from oslo_log import log as logging

from nova import exception
from nova.i18n import _, _LE
from nova import image
from nova import utils

LOG = logging.getLogger(__name__)
IMAGE_API = image.API()

IO_THREAD_SLEEP_TIME = .01
GLANCE_POLL_INTERVAL = 5
CHUNK_SIZE = 64 * 1024  # default chunk size for image transfer


class ThreadSafePipe(queue.LightQueue):
    """The pipe to hold the data which the reader writes to and the writer
    reads from.
    """

    def __init__(self, maxsize, transfer_size):
        queue.LightQueue.__init__(self, maxsize)
        self.transfer_size = transfer_size
        self.transferred = 0

    def read(self, chunk_size):
        """Read data from the pipe.

        Chunksize if ignored for we have ensured
        that the data chunks written to the pipe by readers is the same as the
        chunks asked for by the Writer.
        """
        if self.transfer_size == 0 or self.transferred < self.transfer_size:
            data_item = self.get()
            self.transferred += len(data_item)
            return data_item
        else:
            return ""

    def write(self, data):
        """Put a data item in the pipe."""
        self.put(data)

    def seek(self, offset, whence=0):
        """Set the file's current position at the offset."""
        pass

    def tell(self):
        """Get size of the file to be read."""
        return self.transfer_size

    def close(self):
        """A place-holder to maintain consistency."""
        pass


class GlanceWriteThread(object):
    """Ensures that image data is written to in the glance client and that
    it is in correct ('active')state.
    """

    def __init__(self, context, input, image_id,
            image_meta=None):
        if not image_meta:
            image_meta = {}

        self.context = context
        self.input = input
        self.image_id = image_id
        self.image_meta = image_meta
        self._running = False

    def start(self):
        self.done = event.Event()

        def _inner():
            """Function to do the image data transfer through an update
            and thereon checks if the state is 'active'.
            """
            try:
                IMAGE_API.update(self.context,
                                 self.image_id,
                                 self.image_meta,
                                 data=self.input)
                self._running = True
            except exception.ImageNotAuthorized as exc:
                self.done.send_exception(exc)

            while self._running:
                try:
                    image_meta = IMAGE_API.get(self.context,
                                               self.image_id)
                    image_status = image_meta.get("status")
                    if image_status == "active":
                        self.stop()
                        self.done.send(True)
                    # If the state is killed, then raise an exception.
                    elif image_status == "killed":
                        self.stop()
                        msg = (_("Glance image %s is in killed state") %
                                 self.image_id)
                        LOG.error(msg)
                        self.done.send_exception(exception.NovaException(msg))
                    elif image_status in ["saving", "queued"]:
                        greenthread.sleep(GLANCE_POLL_INTERVAL)
                    else:
                        self.stop()
                        msg = _("Glance image "
                                    "%(image_id)s is in unknown state "
                                    "- %(state)s") % {
                                            "image_id": self.image_id,
                                            "state": image_status}
                        LOG.error(msg)
                        self.done.send_exception(exception.NovaException(msg))
                except Exception as exc:
                    self.stop()
                    self.done.send_exception(exc)

        utils.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()

    def close(self):
        pass


class IOThread(object):
    """Class that reads chunks from the input file and writes them to the
    output file till the transfer is completely done.
    """

    def __init__(self, input, output):
        self.input = input
        self.output = output
        self._running = False
        self.got_exception = False

    def start(self):
        self.done = event.Event()

        def _inner():
            """Read data from the input and write the same to the output
            until the transfer completes.
            """
            self._running = True
            while self._running:
                try:
                    data = self.input.read(CHUNK_SIZE)
                    if not data:
                        self.stop()
                        self.done.send(True)
                    self.output.write(data)
                    greenthread.sleep(IO_THREAD_SLEEP_TIME)
                except Exception as exc:
                    self.stop()
                    LOG.exception(_LE('Read/Write data failed'))
                    self.done.send_exception(exc)

        utils.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()
