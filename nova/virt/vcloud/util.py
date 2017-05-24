'''
Created on 2015.3.11

@author: Administrator
'''
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

"""Classes to handle image files

Collection of classes to handle image upload/download to/from Image service
(like Glance image storage and retrieval service) from/to ESX/ESXi server.

"""


# import six.moves.urllib.parse as urlparse
from eventlet import event
from eventlet import greenthread
from eventlet import queue

from nova import exception
from nova.i18n import _
from nova import image
from nova.openstack.common import log as logging

from nova import utils
from nova import exception
from nova.openstack.common import log as logging
# from nova.virt.vmwareapi import io_util


LOG = logging.getLogger(__name__)
IMAGE_API = image.API()
IO_THREAD_SLEEP_TIME = .01
GLANCE_POLL_INTERVAL = 5

READ_CHUNKSIZE = 65536
QUEUE_BUFFER_SIZE = 10


class GlanceFileRead(object):
    """Glance file read handler class."""

    def __init__(self, glance_read_iter):
        self.glance_read_iter = glance_read_iter
        self.iter = self.get_next()

    def read(self, chunk_size):
        """Read an item from the queue.

        The chunk size is ignored for the Client ImageBodyIterator
        uses its own CHUNKSIZE.
        """
        try:
            return self.iter.next()
        except StopIteration:
            return ""

    def get_next(self):
        """Get the next item from the image iterator."""
        for data in self.glance_read_iter:
            yield data

    def close(self):
        """A dummy close just to maintain consistency."""
        pass


class HybridFileHandle(file):
    
    def __init__(self, *args):
        self.file = open(*args)
    
    def read(self, *args, **kwargs):
        return self.file.read(READ_CHUNKSIZE)
    
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
                    data = self.input.read(None)
                    
                    if not data:
                        self.stop()
                        self.done.send(True)
                    self.output.write(data)
                    greenthread.sleep(IO_THREAD_SLEEP_TIME)
                except Exception as exc:
                    self.stop()
                    LOG.exception(exc)
                    self.done.send_exception(exc)

        greenthread.spawn(_inner)
        return self.done

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()

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
        if self.transferred < self.transfer_size:
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
        
def start_transfer(context, read_file_handle, data_size,
        write_file_handle=None, image_id=None, image_meta=None):
    """Start the data transfer from the reader to the writer.
    Reader writes to the pipe and the writer reads from the pipe. This means
    that the total transfer time boils down to the slower of the read/write
    and not the addition of the two times.
    """

    if not image_meta:
        image_meta = {}

    # The pipe that acts as an intermediate store of data for reader to write
    # to and writer to grab from.
    thread_safe_pipe = ThreadSafePipe(QUEUE_BUFFER_SIZE, data_size)
    # The read thread. In case of glance it is the instance of the
    # GlanceFileRead class. The glance client read returns an iterator
    # and this class wraps that iterator to provide datachunks in calls
    # to read.
    read_thread = IOThread(read_file_handle, thread_safe_pipe)

    # In case of Glance - VMware transfer, we just need a handle to the
    # HTTP Connection that is to send transfer data to the VMware datastore.
    if write_file_handle:
        write_thread = IOThread(thread_safe_pipe, write_file_handle)
    # In case of VMware - Glance transfer, we relinquish VMware HTTP file read
    # handle to Glance Client instance, but to be sure of the transfer we need
    # to be sure of the status of the image on glance changing to active.
    # The GlanceWriteThread handles the same for us.
    elif image_id:
        write_thread = GlanceWriteThread(context, thread_safe_pipe,
                image_id, image_meta)
    # Start the read and write threads.
    read_event = read_thread.start()
    write_event = write_thread.start()
    try:
        # Wait on the read and write events to signal their end
        read_event.wait()
        write_event.wait()
    except Exception as exc:
        # In case of any of the reads or writes raising an exception,
        # stop the threads so that we un-necessarily don't keep the other one
        # waiting.
        read_thread.stop()
        write_thread.stop()

        # Log and raise the exception.
        LOG.exception(exc)
        raise exception.NovaException(exc)
    finally:
        # No matter what, try closing the read and write handles, if it so
        # applies.
        read_file_handle.close()
        if write_file_handle:
            write_file_handle.close()
