..
      Copyright 2010-2011 OpenStack Foundation
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

.. TODO::

   This should be merged into contributor/api

Adding a Method to the OpenStack API
====================================

The interface is a mostly RESTful API. REST stands for Representational State Transfer and provides an architecture "style" for distributed systems using HTTP for transport. Figure out a way to express your request and response in terms of resources that are being created, modified, read, or destroyed.

Routing
-------

To map URLs to controllers+actions, OpenStack uses the Routes package, a clone of Rails routes for Python implementations. See http://routes.readthedocs.io/en/latest/ for more information.

URLs are mapped to "action" methods on "controller" classes in ``nova/api/openstack/__init__/ApiRouter.__init__`` .

See http://routes.readthedocs.io/en/latest/modules/mapper.html for all syntax, but you'll probably just need these two:
   - mapper.connect() lets you map a single URL to a single action on a controller.
   - mapper.resource() connects many standard URLs to actions on a controller.

Controllers and actions
-----------------------

Controllers live in ``nova/api/openstack``, and inherit from nova.wsgi.Controller.

See ``nova/api/openstack/compute/servers.py`` for an example.

Action methods take parameters that are sucked out of the URL by mapper.connect() or .resource().  The first two parameters are self and the WebOb request, from which you can get the req.environ, req.body, req.headers, etc.

Serialization
-------------

Actions return a dictionary, and wsgi.Controller serializes that to JSON.

Faults
------

If you need to return a non-200, you should
return faults.Fault(webob.exc.HTTPNotFound())
replacing the exception as appropriate.
