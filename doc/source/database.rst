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

Database Programming Guide
==========================

::

    TODO(todd): should sqlalchemy.api be here?
                pep-256 on db/api.py and models.py (periods)
                document register_models (where should it be called from?)
                document any relevant test cases
                document flags

The :mod:`api` Module
---------------------

.. automodule:: nova.db.api
    :members:
    :undoc-members:
    :show-inheritance:


Drivers
-------

The :mod:`sqlalchemy` Driver
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: nova.db.sqlalchemy.api
    :members:
    :undoc-members:
    :show-inheritance:


.. automodule:: nova.db.sqlalchemy.models
    :members:
    :undoc-members:
    :show-inheritance:

