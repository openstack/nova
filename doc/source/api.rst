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

API Endpoint Programming Guide
==============================

::

    TODO(todd): get actual docstrings from ec2/osapi_verions instead of @wsgify

Nova has a system for managing multiple APIs on different subdomains.
Currently there is support for the OpenStack API, as well as the Amazon EC2
API.

Common Components
-----------------

The :mod:`nova.api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.cloud
    :members:
    :undoc-members:
    :show-inheritance:

OpenStack API
-------------

The :mod:`openstack` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.auth
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`backup_schedules` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.backup_schedules
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.faults
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`flavors` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.flavors
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.images
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`ratelimiting` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.ratelimiting
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`servers` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.servers
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`sharedipgroups` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.sharedipgroups
    :members:
    :undoc-members:
    :show-inheritance:

EC2 API
-------

The :mod:`nova.api.ec2` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`admin` Module
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.admin
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`apirequest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.apirequest
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.cloud
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.images
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`metadatarequesthandler` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.metadatarequesthandler
    :members:
    :undoc-members:
    :show-inheritance:
