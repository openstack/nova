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

from nova.common import deprecated
from nova import exception
from nova import flags
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova import utils
from nova.virt import driver

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

known_drivers = {
    'baremetal': 'baremetal.BareMetalDriver',
    'fake': 'fake.FakeDriver',
    'libvirt': 'libvirt.LibvirtDriver',
    'vmwareapi': 'vmwareapi.VMWareESXDriver',
    'xenapi': 'xenapi.XenAPIDriver'
    }


def get_connection(read_only=False):
    """
    Returns an object representing the connection to a virtualization
    platform, or to an on-demand bare-metal provisioning platform.

    This could be :mod:`nova.virt.fake.FakeConnection` in test mode,
    a connection to KVM, QEMU, or UML via :mod:`libvirt_conn`, or a connection
    to XenServer or Xen Cloud Platform via :mod:`xenapi`. Other platforms are
    also supported.

    Any object returned here must conform to the interface documented by
    :mod:`FakeConnection`.

    **Related flags**

    :connection_type:  A string literal that falls through an if/elif structure
                       to determine what virtualization mechanism to use.
                       Values may be

                            * fake
                            * libvirt
                            * xenapi
                            * vmwareapi
                            * baremetal

    """
    deprecated.warn(_('Specifying virt driver via connection_type is '
                      'deprecated. Use compute_driver=classname instead.'))

    driver_name = known_drivers.get(FLAGS.connection_type)

    if driver_name is None:
        raise exception.VirtDriverNotFound(name=FLAGS.connection_type)

    conn = importutils.import_object_ns('nova.virt', driver_name,
                                        read_only=read_only)

    if conn is None:
        LOG.error(_('Failed to open connection to underlying virt platform'))
        sys.exit(1)
    return utils.check_isinstance(conn, driver.ComputeDriver)
