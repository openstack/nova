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

API Endpoint
============

Nova has a system for managing multiple APIs on different subdomains.
Currently there is support for the OpenStack API, as well as the Amazon EC2
API.

Common Components
-----------------

The :mod:`nova.api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`nova.api.cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.cloud
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

OpenStack API
-------------

The :mod:`openstack` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.auth
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`backup_schedules` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.backup_schedules
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.faults
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`flavors` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.flavors
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`ratelimiting` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.ratelimiting
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`servers` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.servers
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`sharedipgroups` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. automodule:: nova.api.openstack.sharedipgroups
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

EC2 API
-------

The :mod:`nova.api.ec2` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`admin` Module
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.admin
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`apirequest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.apirequest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud` Module
~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.cloud
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`images` Module
~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`metadatarequesthandler` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.api.ec2.metadatarequesthandler
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

Tests
-----

The :mod:`api_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api_unittest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api_integration` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api_integration
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`cloud_unittest` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.cloud_unittest
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api.fakes` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.fakes
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`api.test_wsgi` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.test_wsgi
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_api` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_api
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_auth` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_auth
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_faults` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_faults
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_flavors` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_flavors
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_images` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_images
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_ratelimiting` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_ratelimiting
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_servers` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_servers
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

The :mod:`test_sharedipgroups` Module
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.tests.api.openstack.test_sharedipgroups
    :noindex:
    :members:
    :undoc-members:
    :show-inheritance:

