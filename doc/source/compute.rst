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


Virtualization Programming Guide
================================

This page contains the Compute Package documentation.


::

    TODO(todd): * document instance_types and power_states


Manager
-------

Documentation for the compute manager and related files.  For reading about
a specific virtualization backend, read Drivers_.


The :mod:`manager` Module
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.compute.manager
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`connection` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.virt.connection
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`disk` Module
~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.compute.disk
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.virt.images
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`instance_types` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.compute.instance_types
    :members:
    :undoc-members:
    :show-inheritance:


The :mod:`power_state` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.compute.power_state
    :members:
    :undoc-members:
    :show-inheritance:


Drivers
-------

Libvirt Implementations
~~~~~~~~~~~~~~~~~~~~~~~

The libvirt driver is capable of supporting KVM, QEMU, and UML.

The :mod:`libvirt_conn` Module
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: nova.virt.libvirt_conn
    :members:
    :undoc-members:
    :show-inheritance:

XEN
~~~

The :mod:`xenapi` Module
^^^^^^^^^^^^^^^^^^^^^^^^

.. automodule:: nova.virt.xenapi
    :members:
    :undoc-members:
    :show-inheritance:

FAKE
~~~~

.. automodule:: nova.virt.fake
    :members:
    :undoc-members:
    :show-inheritance:

Monitoring
----------

The :mod:`monitor` Module
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.compute.monitor
    :members:
    :undoc-members:
    :show-inheritance:


Tests
-----


The :mod:`compute_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.compute_unittest
    :members:
    :undoc-members:
    :show-inheritance:

