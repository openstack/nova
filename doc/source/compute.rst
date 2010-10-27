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


from etherpad todo
------------------

  * FIX RST IMPORT ERRORS
  * Compute Manager
    * public methods
    * responsibilities
  * Compute Driver
    * public methods
    * libvirt implementation (kvm/qemu vs uml)
    * xen implementation
    * hyperv implementation


Compute Documentation
=====================

This page contains the Compute Package documentation.


The :mod:`manager` Module
-------------------------

.. automodule:: nova.compute.manager
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`disk` Module
----------------------

.. automodule:: nova.compute.disk
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`instance_types` Module
--------------------------------

.. automodule:: nova.compute.instance_types
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`power_state` Module
-----------------------------

.. automodule:: nova.compute.power_state
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`monitor` Module
-------------------------

.. automodule:: nova.compute.monitor
    :members:
    :undoc-members:
    :show-inheritance:

RELATED TESTS
-------------

The :mod:`compute_unittest` Module
----------------------------------

.. automodule:: nova.tests.compute_unittest
    :members:
    :undoc-members:
    :show-inheritance:

