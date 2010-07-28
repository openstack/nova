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

Welcome to nova's documentation!
================================

Nova is a cloud computing fabric controller (the main part of an IaaS system) built to match the popular AWS EC2 and S3 APIs. 
It is written in Python, using the Tornado and Twisted frameworks, and relies on the standard AMQP messaging protocol, 
and the Redis distributed KVS.
Nova is intended to be easy to extend, and adapt. For example, it currently uses 
an LDAP server for users and groups, but also includes a fake LDAP server,
that stores data in Redis. It has extensive test coverage, and uses the 
Sphinx toolkit (the same as Python itself) for code and user documentation.
While Nova is currently in Beta use within several organizations, the codebase
is very much under active development - there are bugs!

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

