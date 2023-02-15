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

import os

from oslo_log import log as logging

from nova import exception

LOG = logging.getLogger(__name__)


SYS = '/sys'


# NOTE(bauzas): this method is deliberately not wrapped in a privsep entrypoint
def read_sys(path: str) -> str:
    """Reads the content of a file in the sys filesystem.

    :param path: relative or absolute. If relative, will be prefixed by /sys.
    :returns: contents of that file.
    :raises: nova.exception.FileNotFound if we can't read that file.
    """
    try:
        # The path can be absolute with a /sys prefix but that's fine.
        with open(os.path.join(SYS, path), mode='r') as data:
            return data.read()
    except (OSError, ValueError) as exc:
        raise exception.FileNotFound(file_path=path) from exc


# NOTE(bauzas): this method is deliberately not wrapped in a privsep entrypoint
# In order to correctly use it, you need to decorate the caller with a specific
# privsep entrypoint.
def write_sys(path: str, data: str) -> None:
    """Writes the content of a file in the sys filesystem with data.

    :param path: relative or absolute. If relative, will be prefixed by /sys.
    :param data: the data to write.
    :returns: contents of that file.
    :raises: nova.exception.FileNotFound if we can't write that file.
    """
    try:
        # The path can be absolute with a /sys prefix but that's fine.
        with open(os.path.join(SYS, path), mode='w') as fd:
            fd.write(data)
    except (OSError, ValueError) as exc:
        raise exception.FileNotFound(file_path=path) from exc
