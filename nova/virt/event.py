# Copyright 2013 Red Hat, Inc.
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
Asynchronous event notifications from virtualization drivers.

This module defines a set of classes representing data for
various asynchronous events that can occur in a virtualization
driver.
"""

import time

EVENT_LIFECYCLE_STARTED = 0
EVENT_LIFECYCLE_STOPPED = 1
EVENT_LIFECYCLE_PAUSED = 2
EVENT_LIFECYCLE_RESUMED = 3


class Event(object):
    """Base class for all events emitted by a hypervisor.

    All events emitted by a virtualization driver are
    subclasses of this base object. The only generic
    information recorded in the base class is a timestamp
    indicating when the event first occurred. The timestamp
    is recorded as fractional seconds since the UNIX epoch.
    """

    def __init__(self, timestamp=None):
        if timestamp is None:
            self.timestamp = time.time()
        else:
            self.timestamp = timestamp

    def get_timestamp(self):
        return self.timestamp


class InstanceEvent(Event):
    """Base class for all instance events.

    All events emitted by a virtualization driver which
    are associated with a virtual domain instance are
    subclasses of this base object. This object records
    the UUID associated with the instance.
    """

    def __init__(self, uuid, timestamp=None):
        super(InstanceEvent, self).__init__(timestamp)

        self.uuid = uuid

    def get_instance_uuid(self):
        return self.uuid


class LifecycleEvent(InstanceEvent):
    """Class for instance lifecycle state change events.

    When a virtual domain instance lifecycle state changes,
    events of this class are emitted. The EVENT_LIFECYCLE_XX
    constants defined why lifecycle change occurred. This
    event allows detection of an instance starting/stopping
    without need for polling.
    """

    def __init__(self, uuid, transition, timestamp=None):
        super(LifecycleEvent, self).__init__(uuid, timestamp)

        self.transition = transition

    def get_transition(self):
        return self.transition
