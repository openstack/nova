..
      Copyright 2010-2011 United States Government as represented by the
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

Services, Managers and Drivers
==============================

The responsibilities of Services, Managers, and Drivers, can be a bit confusing to people that are new to nova.  This document attempts to outline the division of responsibilities to make understanding the system a little bit easier.

Currently, Managers and Drivers are specified by flags and loaded using utils.load_object().  This method allows for them to be implemented as singletons, classes, modules or objects.  As long as the path specified by the flag leads to an object (or a callable that returns an object) that responds to getattr, it should work as a manager or driver.


The :mod:`nova.service` Module
------------------------------

.. automodule:: nova.service
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`nova.manager` Module
------------------------------

.. automodule:: nova.manager
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:


Implementation-Specific Drivers
-------------------------------

A manager will generally load a driver for some of its tasks. The driver is responsible for specific implementation details.  Anything running shell commands on a host, or dealing with other non-python code should probably be happening in a driver.

Drivers should not touch the database as the database management is done inside `nova-conductor`.

It usually makes sense to define an Abstract Base Class for the specific driver (i.e. VolumeDriver), to define the methods that a different driver would need to implement.
