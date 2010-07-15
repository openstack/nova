# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
A fake (in-memory) hypervisor+api. Allows nova testing w/o KVM and libvirt.
"""

import StringIO
from xml.etree import ElementTree


class FakeVirtConnection(object):
    # FIXME: networkCreateXML, listNetworks don't do anything since
    # they aren't exercised in tests yet

    def __init__(self):
        self.next_index = 0
        self.instances = {}

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def lookupByID(self, i):
        return self.instances[str(i)]

    def listDomainsID(self):
        return self.instances.keys()

    def listNetworks(self):
        return []

    def lookupByName(self, instance_id):
        for x in self.instances.values():
            if x.name() == instance_id:
                return x
        raise Exception('no instance found for instance_id: %s' % instance_id)

    def networkCreateXML(self, xml):
        pass

    def createXML(self, xml, flags):
        # parse the xml :(
        xml_stringio = StringIO.StringIO(xml)

        my_xml = ElementTree.parse(xml_stringio)
        name = my_xml.find('name').text

        fake_instance = FakeVirtInstance(conn=self,
                                         index=str(self.next_index),
                                         name=name,
                                         xml=my_xml)
        self.instances[str(self.next_index)] = fake_instance
        self.next_index += 1

    def _removeInstance(self, i):
        self.instances.pop(str(i))


class FakeVirtInstance(object):
    NOSTATE = 0x00
    RUNNING = 0x01
    BLOCKED = 0x02
    PAUSED = 0x03
    SHUTDOWN = 0x04
    SHUTOFF = 0x05
    CRASHED = 0x06

    def __init__(self, conn, index, name, xml):
        self._conn = conn
        self._destroyed = False
        self._name = name
        self._index = index
        self._state = self.RUNNING

    def name(self):
        return self._name

    def destroy(self):
        if self._state == self.SHUTOFF:
            raise Exception('instance already destroyed: %s' % self.name())
        self._state = self.SHUTDOWN
        self._conn._removeInstance(self._index)

    def info(self):
        return [self._state, 0, 2, 0, 0]

    def XMLDesc(self, flags):
        return open('fakevirtinstance.xml', 'r').read()

    def blockStats(self, disk):
        return [0L, 0L, 0L, 0L, null]

    def interfaceStats(self, iface):
        return [0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L]
