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

Welcome to Nova's documentation!
================================

Nova is a cloud computing fabric controller (the main part of an IaaS system). 
It is written in Python and relies on the standard AMQP messaging protocol, uses the Twisted framework,
and optionally uses the Redis distributed key value store for authorization.

Nova is intended to be easy to extend and adapt. For example, authentication and authorization
requests by default use an RDBMS-backed datastore driver.  However, there is already support
for using LDAP backing authentication (slapd) and if you wish to "fake" LDAP, there is a module
available that uses ReDIS to store authentication information in an LDAP-like backing datastore. 
It has extensive test coverage, and uses the Sphinx toolkit (the same as Python itself) for code 
and developer documentation. Additional documentation is available on the 
'OpenStack wiki <http://wiki.openstack.org>'_.
While Nova is currently in Beta use within several organizations, the codebase
is very much under active development - please test it and log bugs!

Contents:

.. toctree::
   :maxdepth: 2
                   
   getting.started  
   architecture
   network      
   storage
   auth  
   compute
   endpoint
   nova
   fakes
   binaries
   modules
   packages

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

