# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Grid Dynamics
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

import abc

from nova.virt import images
from nova.virt.libvirt import utils as libvirt_utils


class Snapshot(object):
    @abc.abstractmethod
    def create(self):
        """Create new snapshot"""
        pass

    @abc.abstractmethod
    def extract(self, target, out_format):
        """Extract snapshot content to file

        :target: path to extraction
        :out_format: format of extraction (raw, qcow2, ...)
        """
        pass

    @abc.abstractmethod
    def delete(self):
        """Delete snapshot"""
        pass


class RawSnapshot(object):
    def __init__(self, path, name):
        self.path = path
        self.name = name

    def create(self):
        pass

    def extract(self, target, out_format):
        images.convert_image(self.path, target, out_format)

    def delete(self):
        pass


class Qcow2Snapshot(object):
    def __init__(self, path, name):
        self.path = path
        self.name = name

    def create(self):
        libvirt_utils.create_snapshot(self.path, self.name)

    def extract(self, target, out_format):
        libvirt_utils.extract_snapshot(self.path, 'qcow2',
                                       self.name, target,
                                       out_format)

    def delete(self):
        libvirt_utils.delete_snapshot(self.path, self.name)


class LvmSnapshot(object):
    def __init__(self, path, name):
        self.path = path
        self.name = name

    def create(self):
        raise NotImplementedError(_("LVM snapshots not implemented"))

    def extract(self, target, out_format):
        raise NotImplementedError(_("LVM snapshots not implemented"))

    def delete(self):
        raise NotImplementedError(_("LVM snapshots not implemented"))
