..
      Copyright 2010 United States Government as represented by the
      Administrator of the National Aeronautics and Space Administration.
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

.. _service_manager_driver:

Services Managers and Drivers
=============================

The responsibilities of Services, Managers, and Drivers, can be a bit confusing to people that are new to nova.  This document attempts to outline the division of responsibilities to make understanding the system a little bit easier.

Currently, Managers and Drivers are specified by flags and loaded using utils.load_object().  This method allows for them to be implemented as singletons, classes, modules or objects.  As long as the path specified by the flag leads to an object (or a callable that returns an object) that responds to getattr, it should work as a manager or driver.

Service
-------

A service is a very thin wrapper around a Manager object.  It exposes the manager's public methods to other components of the system via rpc.  It will report state periodically to the database and is responsible for initiating any periodic tasts that need to be executed on a given host.

The :mod:`service` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.service
    :members:
    :undoc-members:
    :show-inheritance:

Manager
-------

Managers are responsible for a certain aspect of the sytem.  It is a logical grouping of code relating to a portion of the system.  In general other components should be using the manager to make changes to the components that it is responsible for.

For example, other components that need to deal with volumes in some way, should do so by calling methods on the VolumeManager instead of directly changing fields in the database.  This allows us to keep all of the code relating to volumes in the same place.

We have adopted a basic strategy of Smart managers and dumb data, which means rather than attaching methods to data objects, components should call manager methods that act on the data.

Methods on managers that can be executed locally should be called directly. If a particular method must execute on a remote host, this should be done via rpc to the service that wraps the manager

Managers should be responsible for most of the db access, and non-implementation specific data.  Anything implementation specific that can't be generalized should be done by the Driver.

In general, we prefer to have one manager with multiple drivers for different implementations, but sometimes it makes sense to have multiple managers.  You can think of it this way: Abstract different overall strategies at the manager level(FlatNetwork vs VlanNetwork), and different implementations at the driver level(LinuxNetDriver vs CiscoNetDriver).

Managers will often provide methods for initial setup of a host or periodic tasksto a wrapping service.

The :mod:`manager` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.manager
    :members:
    :undoc-members:
    :show-inheritance:

Driver
------

A manager will generally load a driver for some of its tasks. The driver is responsible for specific implementation details.  Anything running shell commands on a host, or dealing with other non-python code should probably be happening in a driver.

Drivers should minimize touching the database, although it is currently acceptable for implementation specific data. This may be reconsidered at some point.

It usually makes sense to define an Abstract Base Class for the specific driver (i.e. VolumeDriver), to define the methods that a different driver would need to implement.
