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
import logging
import os
import stat
import tempfile

from oslo_utils import excutils

LOG = logging.getLogger(__name__)

_FILE_CACHE = {}
DEFAULT_MODE = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO


def ensure_tree(path, mode=DEFAULT_MODE):
    """Create a directory (and any ancestor directories required)

    :param path: Directory to create
    :param mode: Directory creation permissions
    """
    try:
        os.makedirs(path, mode)
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

    if force_reload:
        delete_cached_file(filename)

    reloaded = False
    mtime = os.path.getmtime(filename)
    cache_info = _FILE_CACHE.setdefault(filename, {})

    if not cache_info or mtime > cache_info.get('mtime', 0):
        LOG.debug("Reloading cached file %s" % filename)
        with open(filename) as fap:
            cache_info['data'] = fap.read()
        cache_info['mtime'] = mtime
        reloaded = True
    return (reloaded, cache_info['data'])


def delete_cached_file(filename):
    """Delete cached file if present.

    :param filename: filename to delete
    """
    global _FILE_CACHE

    if filename in _FILE_CACHE:
        del _FILE_CACHE[filename]


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

    see built-in open() documentation for more details

    Note: The reason this is kept in a separate module is to easily
    be able to provide a stub module that doesn't alter system
    state at all (for unit tests)
    """
    return open(*args, **kwargs)


def write_to_tempfile(content, path=None, suffix='', prefix='tmp'):
    """Create temporary file or use existing file.

    This util is needed for creating temporary file with
    specified content, suffix and prefix. If path is not None,
    it will be used for writing content. If the path doesn't
    exist it'll be created.

    :param content: content for temporary file.
    :param path: same as parameter 'dir' for mkstemp
    :param suffix: same as parameter 'suffix' for mkstemp
    :param prefix: same as parameter 'prefix' for mkstemp

    For example: it can be used in database tests for creating
    configuration files.
    """
    if path:
        ensure_tree(path)

    (fd, path) = tempfile.mkstemp(suffix=suffix, dir=path, prefix=prefix)
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    return path
