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

"""Functions to address filesystem calls, particularly sysfs."""

import functools
import os
import time

from oslo_log import log as logging

from nova import exception

LOG = logging.getLogger(__name__)
SYS = '/sys'
RETRY_LIMIT = 5


# a retry decorator to handle EBUSY
def retry_if_busy(func):
    """Decorator to retry a function if it raises DeviceBusy.

    This decorator will retry the function RETRY_LIMIT=5 times if it raises
    DeviceBusy. It will sleep for 1 second on the first retry, 2 seconds on
    the second retry, and so on, up to RETRY_LIMIT seconds. If the function
    still raises DeviceBusy after RETRY_LIMIT retries, the exception will be
    raised.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for i in range(RETRY_LIMIT):
            try:
                return func(*args, **kwargs)
            except exception.DeviceBusy as e:
                # if we have retried RETRY_LIMIT times, raise the exception
                # otherwise, sleep and retry, i is 0-based so we need
                # to add 1 to it
                count = i + 1
                if count < RETRY_LIMIT:
                    LOG.debug(
                        f"File {e.kwargs['file_path']} is busy, "
                        f"sleeping {count} seconds before retrying")
                    time.sleep(count)
                    continue
                raise
    return wrapper

# NOTE(bauzas): this method is deliberately not wrapped in a privsep entrypoint


@retry_if_busy
def read_sys(path: str) -> str:
    """Reads the content of a file in the sys filesystem.

    :param path: relative or absolute. If relative, will be prefixed by /sys.
    :returns: contents of that file.
    :raises: nova.exception.FileNotFound if we can't read that file.
    :raises: nova.exception.DeviceBusy if the file is busy.
    """
    try:
        # The path can be absolute with a /sys prefix but that's fine.
        with open(os.path.join(SYS, path), mode='r') as data:
            return data.read()
    except OSError as exc:
        # errno 16 is EBUSY, which means the file is busy.
        if exc.errno == 16:
            raise exception.DeviceBusy(file_path=path) from exc
        # convert permission denied to file not found
        raise exception.FileNotFound(file_path=path) from exc
    except ValueError as exc:
        raise exception.FileNotFound(file_path=path) from exc


# NOTE(bauzas): this method is deliberately not wrapped in a privsep entrypoint
# In order to correctly use it, you need to decorate the caller with a specific
# privsep entrypoint.
@retry_if_busy
def write_sys(path: str, data: str) -> None:
    """Writes the content of a file in the sys filesystem with data.

    :param path: relative or absolute. If relative, will be prefixed by /sys.
    :param data: the data to write.
    :returns: contents of that file.
    :raises: nova.exception.FileNotFound if we can't write that file.
    :raises: nova.exception.DeviceBusy if the file is busy.
    """
    try:
        # The path can be absolute with a /sys prefix but that's fine.
        with open(os.path.join(SYS, path), mode='w') as fd:
            fd.write(data)
    except OSError as exc:
        # errno 16 is EBUSY, which means the file is busy.
        if exc.errno == 16:
            raise exception.DeviceBusy(file_path=path) from exc
        # convert permission denied to file not found
        raise exception.FileNotFound(file_path=path) from exc
    except ValueError as exc:
        raise exception.FileNotFound(file_path=path) from exc
