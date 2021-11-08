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
from nova.virt import event


class LibvirtEvent(event.InstanceEvent):
    """Base class for virt events that are specific to libvirt and therefore
    handled in the libvirt driver level instead of propagatig it up to the
    compute manager.
    """


class DeviceEvent(LibvirtEvent):
    """Base class for device related libvirt events"""

    def __init__(self, uuid: str, dev: str, timestamp: float = None):
        super().__init__(uuid, timestamp)
        self.dev = dev

    def __repr__(self) -> str:
        return "<%s: %s, %s => %s>" % (
            self.__class__.__name__,
            self.timestamp,
            self.uuid,
            self.dev)


class DeviceRemovedEvent(DeviceEvent):
    """Libvirt sends this event after a successful device detach"""


class DeviceRemovalFailedEvent(DeviceEvent):
    """Libvirt sends this event after an unsuccessful device detach"""
