# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# Copyright 2018 Michael Still and Aptira
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

# This module is utility methods that privsep depends on. Privsep isn't allowed
# to depend on anything outside the privsep directory, so these need to be
# here. That said, other parts of nova can call into these utilities if
# needed.

import errno
import mmap
import os
import random
import sys

from oslo_log import log as logging
from oslo_utils import excutils

import nova.privsep

# NOTE(mriedem): Avoid importing nova.utils since that can cause a circular
# import with the privsep code. In fact, avoid importing anything outside
# of nova/privsep/ if possible.

LOG = logging.getLogger(__name__)


def generate_random_string():
    return str(random.randint(0, sys.maxsize))


def supports_direct_io(dirpath):

    if not hasattr(os, 'O_DIRECT'):
        LOG.debug("This python runtime does not support direct I/O")
        return False

    # Use a random filename to avoid issues with $dirpath being on shared
    # storage.
    file_name = "%s.%s" % (".directio.test", generate_random_string())
    testfile = os.path.join(dirpath, file_name)

    hasDirectIO = True
    fd = None
    try:
        fd = os.open(testfile, os.O_CREAT | os.O_WRONLY | os.O_DIRECT)
        # Check is the write allowed with 4096 byte alignment
        align_size = 4096
        m = mmap.mmap(-1, align_size)
        m.write(b"x" * align_size)
        os.write(fd, m)
        LOG.debug("Path '%(path)s' supports direct I/O",
                  {'path': dirpath})
    except OSError as e:
        if e.errno in (errno.EINVAL, errno.ENOENT):
            LOG.debug("Path '%(path)s' does not support direct I/O: "
                      "'%(ex)s'", {'path': dirpath, 'ex': e})
            hasDirectIO = False
        else:
            with excutils.save_and_reraise_exception():
                LOG.error("Error on '%(path)s' while checking "
                          "direct I/O: '%(ex)s'",
                          {'path': dirpath, 'ex': e})
    except Exception as e:
        with excutils.save_and_reraise_exception():
            LOG.error("Error on '%(path)s' while checking direct I/O: "
                      "'%(ex)s'", {'path': dirpath, 'ex': e})
    finally:
        # ensure unlink(filepath) will actually remove the file by deleting
        # the remaining link to it in close(fd)
        if fd is not None:
            os.close(fd)

        try:
            os.unlink(testfile)
        except Exception:
            pass

    return hasDirectIO


@nova.privsep.sys_admin_pctxt.entrypoint
def kill(pid, signal):
    os.kill(pid, signal)
