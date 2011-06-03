# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""Abstraction of the underlying virtualization API."""

import sys

from nova import flags
from nova import log as logging
from nova import utils
from nova.virt import driver
from nova.virt import fake
from nova.virt import hyperv
from nova.virt import vmwareapi_conn
from nova.virt import xenapi_conn
from nova.virt.libvirt import connection as libvirt_conn


LOG = logging.getLogger("nova.virt.connection")
FLAGS = flags.FLAGS


def get_connection(read_only=False):
    """
    Returns an object representing the connection to a virtualization
    platform.

    This could be :mod:`nova.virt.fake.FakeConnection` in test mode,
    a connection to KVM, QEMU, or UML via :mod:`libvirt_conn`, or a connection
    to XenServer or Xen Cloud Platform via :mod:`xenapi`.

    Any object returned here must conform to the interface documented by
    :mod:`FakeConnection`.

    **Related flags**

    :connection_type:  A string literal that falls through a if/elif structure
                       to determine what virtualization mechanism to use.
                       Values may be

                            * fake
                            * libvirt
                            * xenapi
    """
    # TODO(termie): maybe lazy load after initial check for permissions
    # TODO(termie): check whether we can be disconnected
    t = FLAGS.connection_type
    if t == 'fake':
        conn = fake.get_connection(read_only)
    elif t == 'libvirt':
        conn = libvirt_conn.get_connection(read_only)
    elif t == 'xenapi':
        conn = xenapi_conn.get_connection(read_only)
    elif t == 'hyperv':
        conn = hyperv.get_connection(read_only)
    elif t == 'vmwareapi':
        conn = vmwareapi_conn.get_connection(read_only)
    else:
        raise Exception('Unknown connection type "%s"' % t)

    if conn is None:
        LOG.error(_('Failed to open connection to the hypervisor'))
        sys.exit(1)
    return utils.check_isinstance(conn, driver.ComputeDriver)
