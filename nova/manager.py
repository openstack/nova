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

"""Base Manager class.

Managers are responsible for a certain aspect of the system.  It is a logical
grouping of code relating to a portion of the system.  In general other
components should be using the manager to make changes to the components that
it is responsible for.

For example, other components that need to deal with volumes in some way,
should do so by calling methods on the VolumeManager instead of directly
changing fields in the database.  This allows us to keep all of the code
relating to volumes in the same place.

We have adopted a basic strategy of Smart managers and dumb data, which means
rather than attaching methods to data objects, components should call manager
methods that act on the data.

Methods on managers that can be executed locally should be called directly. If
a particular method must execute on a remote host, this should be done via rpc
to the service that wraps the manager

Managers should be responsible for most of the db access, and
non-implementation specific data.  Anything implementation specific that can't
be generalized should be done by the Driver.

In general, we prefer to have one manager with multiple drivers for different
implementations, but sometimes it makes sense to have multiple managers.  You
can think of it this way: Abstract different overall strategies at the manager
level(FlatNetwork vs VlanNetwork), and different implementations at the driver
level(LinuxNetDriver vs CiscoNetDriver).

Managers will often provide methods for initial setup of a host or periodic
tasks to a wrapping service.

This module provides Manager, a base class for managers.

"""

from oslo_service import periodic_task

import nova.conf
from nova.db import base
from nova import profiler
from nova import rpc


CONF = nova.conf.CONF


class PeriodicTasks(periodic_task.PeriodicTasks):
    def __init__(self):
        super(PeriodicTasks, self).__init__(CONF)


class ManagerMeta(profiler.get_traced_meta(), type(PeriodicTasks)):
    """Metaclass to trace all children of a specific class.

    This metaclass wraps every public method (not starting with _ or __)
    of the class using it. All children classes of the class using ManagerMeta
    will be profiled as well.

    Adding this metaclass requires that the __trace_args__ attribute be added
    to the class we want to modify. That attribute is a dictionary
    with one mandatory key: "name". "name" defines the name
    of the action to be traced (for example, wsgi, rpc, db).

    The OSprofiler-based tracing, although, will only happen if profiler
    instance was initiated somewhere before in the thread, that can only happen
    if profiling is enabled in nova.conf and the API call to Nova API contained
    specific headers.
    """


class Manager(base.Base, PeriodicTasks, metaclass=ManagerMeta):
    __trace_args__ = {"name": "rpc"}

    def __init__(self, host=None, service_name='undefined'):
        if not host:
            host = CONF.host
        self.host = host
        self.backdoor_port = None
        self.service_name = service_name
        self.notifier = rpc.get_notifier(self.service_name, self.host)
        self.additional_endpoints = []
        super(Manager, self).__init__()

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        return self.run_periodic_tasks(context, raise_on_error=raise_on_error)

    def init_host(self):
        """Hook to do additional manager initialization when one requests
        the service be started.  This is called before any service record
        is created.

        Child classes should override this method.
        """
        pass

    def cleanup_host(self):
        """Hook to do cleanup work when the service shuts down.

        Child classes should override this method.
        """
        pass

    def pre_start_hook(self):
        """Hook to provide the manager the ability to do additional
        start-up work before any RPC queues/consumers are created. This is
        called after other initialization has succeeded and a service
        record is created.

        Child classes should override this method.
        """
        pass

    def post_start_hook(self):
        """Hook to provide the manager the ability to do additional
        start-up work immediately after a service creates RPC consumers
        and starts 'running'.

        Child classes should override this method.
        """
        pass

    def reset(self):
        """Hook called on SIGHUP to signal the manager to re-read any
        dynamic configuration or do any reconfiguration tasks.
        """
        pass
