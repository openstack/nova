# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
# Copyright (c) 2011 Piston Cloud Computing, Inc
# Copyright (c) 2012 University Of Minho
# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2015 Red Hat, Inc
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
Manages information about the guest.

This class encapsulates libvirt domain provides certain
higher level APIs around the raw libvirt API. These APIs are
then used by all the other libvirt related classes
"""

from lxml import etree
from oslo_log import log as logging
from oslo_utils import encodeutils
from oslo_utils import excutils
from oslo_utils import importutils

from nova.i18n import _LE
from nova import utils

libvirt = None

LOG = logging.getLogger(__name__)


class Guest(object):

    def __init__(self, domain):

        global libvirt
        if libvirt is None:
            libvirt = importutils.import_module('libvirt')

        self._domain = domain

    def __repr__(self):
        return "<Guest %(id)d %(name)s %(uuid)s>" % {
            'id': self.id,
            'name': self.name,
            'uuid': self.uuid
        }

    @property
    def id(self):
        return self._domain.ID()

    @property
    def uuid(self):
        return self._domain.UUIDString()

    @property
    def name(self):
        return self._domain.name()

    @property
    def _encoded_xml(self):
        return encodeutils.safe_decode(self._domain.XMLDesc(0))

    @classmethod
    def create(cls, xml, host):
        """Create a new Guest

        :param xml: XML definition of the domain to create
        :param host: host.Host connection to define the guest on

        :returns guest.Guest: Guest ready to be launched
        """
        try:
            # TODO(sahid): Host.write_instance_config should return
            # an instance of Guest
            domain = host.write_instance_config(xml)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error defining a domain with XML: %s') %
                          encodeutils.safe_decode(xml))
        return cls(domain)

    def launch(self, pause=False):
        """Starts a created guest.

        :param pause: Indicates whether to start and pause the guest
        """
        flags = pause and libvirt.VIR_DOMAIN_START_PAUSED or 0
        try:
            return self._domain.createWithFlags(flags)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error launching a defined domain '
                              'with XML: %s') %
                          self._encoded_xml, errors='ignore')

    def poweroff(self):
        """Stops a running guest."""
        self._domain.destroy()

    def resume(self):
        """Resumes a suspended guest."""
        self._domain.resume()

    def enable_hairpin(self):
        """Enables hairpin mode for this guest."""
        interfaces = self.get_interfaces()
        try:
            for interface in interfaces:
                utils.execute(
                    'tee',
                    '/sys/class/net/%s/brport/hairpin_mode' % interface,
                    process_input='1',
                    run_as_root=True,
                    check_exit_code=[0, 1])
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error(_LE('Error enabling hairpin mode with XML: %s') %
                          self._encoded_xml, errors='ignore')

    def get_interfaces(self):
        """Returns a list of all network interfaces for this domain."""
        doc = None

        try:
            doc = etree.fromstring(self._encoded_xml)
        except Exception:
            return []

        interfaces = []

        nodes = doc.findall('./devices/interface/target')
        for target in nodes:
            interfaces.append(target.get('dev'))

        return interfaces

    def get_vcpus_info(self):
        """Returns virtual cpus information of guest.

        :returns: objects.VirtVCPUInfo
        """
        vcpus = self._domain.vcpus()
        if vcpus is not None:
            for vcpu in vcpus[0]:
                yield GuestVCPUInfo(
                    id=vcpu[0], cpu=vcpu[3], state=vcpu[1], time=vcpu[2])

    def delete_configuration(self):
        """Undefines a domain from hypervisor."""
        try:
            self._domain.undefineFlags(
                libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE)
        except libvirt.libvirtError:
            LOG.debug("Error from libvirt during undefineFlags. %d"
                      "Retrying with undefine", self.id)
            self._domain.undefine()
        except AttributeError:
            # Older versions of libvirt don't support undefine flags,
            # trying to remove managed image
            try:
                if self._domain.hasManagedSaveImage(0):
                    self._domain.managedSaveRemove(0)
            except AttributeError:
                pass
            self._domain.undefine()


class GuestVCPUInfo(object):
    def __init__(self, id, cpu, state, time):
        """Structure for information about guest vcpus.

        :param id: The virtual cpu number
        :param cpu: The host cpu currently associated
        :param state: The running state of the vcpu (0 offline, 1 running, 2
                      blocked on resource)
        :param time: The cpu time used in nanoseconds
        """
        self.id = id
        self.cpu = cpu
        self.state = state
        self.time = time
