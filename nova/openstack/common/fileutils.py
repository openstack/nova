# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack Foundation.
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


import contextlib
import errno
import os

from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

_FILE_CACHE = {}


def ensure_tree(path):
    """Create a directory (and any ancestor directories required)

    :param path: Directory to create
    """
    try:
        os.makedirs(path)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            if not os.path.isdir(path):
                raise
        else:
            raise


def read_cached_file(filename, force_reload=False):
    """Read from a file if it has been modified.

    :param force_reload: Whether to reload the file.
    :returns: A tuple with a boolean specifying if the data is fresh
              or not.
    """
    global _FILE_CACHE

    if force_reload and filename in _FILE_CACHE:
        del _FILE_CACHE[filename]

    reloaded = False
    mtime = os.path.getmtime(filename)
    cache_info = _FILE_CACHE.setdefault(filename, {})

    if not cache_info or mtime > cache_info.get('mtime', 0):
        LOG.debug(_("Reloading cached file %s") % filename)
        with open(filename) as fap:
            cache_info['data'] = fap.read()
        cache_info['mtime'] = mtime
        reloaded = True
    return (reloaded, cache_info['data'])


def delete_if_exists(path, remove=os.unlink):
    """Delete a file, but ignore file not found error.

    :param path: File to delete
    :param remove: Optional function to remove passed path
    """

    try:
        remove(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


@contextlib.contextmanager
def remove_path_on_error(path, remove=delete_if_exists):
    """Protect code that wants to operate on PATH atomically.
    Any exception will cause PATH to be removed.

    :param path: File to work with
    :param remove: Optional function to remove passed path
    """

    try:
        yield
    except Exception:
        with excutils.save_and_reraise_exception():
            remove(path)


def file_open(*args, **kwargs):
    """Open file

    see built-in file() documentation for more details

    Note: The reason this is kept in a separate module is to easily
    be able to provide a stub module that doesn't alter system
    state at all (for unit tests)
    """
    return file(*args, **kwargs)
