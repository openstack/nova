..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

===============================
 Placement API Developer Notes
===============================

Overview
========

The Nova project introduced the :doc:`placment service <placement>` as part of
the Newton release. The service provides an HTTP API to manage inventories of
different classes of resources, such as disk or virtual cpus, made available by
entities called resource providers. Information provided through the placement
API is intended to enable more effective accounting of resources in an
OpenStack deployment and better scheduling of various entities in the cloud.

The document serves to explain the architecture of the system and to provide
some guidance on how to maintain and extend the code. For more detail on why
the system was created and how it does its job see :doc:`placement`.

Big Picture
===========

The placement service is straightforward: It is a `WSGI`_ application that
sends and receives JSON, using an RDBMS (usually MySQL) for persistence.
As state is managed solely in the DB, scaling the placement service is done by
increasing the number of WSGI application instances and scaling the RDBMS using
traditional database scaling techniques.

For sake of consistency and because there was initially intent to make the
entities in the placement service available over RPC, `versioned objects`_ are
used to provide the interface between the HTTP application layer and the
SQLAlchemy-driven persistence layer. Even without RPC, these objects provide
useful structuring and separation of the code.

Though the placement service doesn't aspire to be a `microservice` it does
aspire to continue to be small and minimally complex. This means a relatively
small amount of middleware that is not configurable, and a limited number of
exposed resources where any given resource is represented by one (and only
one) URL that expresses a noun that is a member of the system. Adding
additional resources should be considered a significant change requiring robust
review from many stakeholders.

The set of HTTP resources represents a concise and constrained grammar for
expressing the management of resource providers, inventories, resource classes
and allocations. If a solution is initially designed to need more resources or
a more complex grammar that may be a sign that we need to give our goals
greater scrutiny. Is there a way to do what we want with what we have already?
Can some other service help? Is a new collaborating service required?

Minimal Framework
=================

The API is set up to use a minimal framework that tries to keep the structure
of the application as discoverable as possible and keeps the HTTP interaction
near the surface. The goal of this is to make things easy to trace when
debugging or adding functionality.

Functionality which is required for every request is handled in raw WSGI
middleware that is composed in the `nova.api.openstack.placement.deploy`
module. Dispatch or routing is handled declaratively via the
``ROUTE_DECLARATIONS`` map defined in the
`nova.api.openstack.placement.handler` module.

Mapping is by URL plus request method. The destination is a complete WSGI
application, using the `wsgify`_  method from `WebOb`_ to provide a
`Request`_ object that provides convenience methods for accessing request
headers, bodies, and query parameters and for generating responses. In the
placement API these mini-applications are called `handlers`.

This division between middleware, dispatch and handlers is supposed to
provide clues on where a particular behavior or functionality should be
implemented. Like most such systems, this doesn't always work but is a useful
tool.

Gotchas
=======

This section tries to shed some light on some of the differences between the
placement API and some of the nova APIs or on situations which may be
surprising or unexpected.

* The placement API is somewhat more strict about `Content-Type` and `Accept`
  headers in an effort to follow the HTTP RFCs.

  If a user-agent sends some JSON in a `PUT` or `POST` request without a
  `Content-Type` of `application/json` the request will result in an error.

  If a `GET` request is made without an `Accept` header, the response will
  default to being `application/json`.

  If a request is made with an explicit `Accept` header that does not include
  `application/json` then there will be an error and the error will attempt to
  be in the requested format (for example, `text/plain`).

* If a URL exists, but a request is made using a method that that URL does not
  support, the API will respond with a `405` error. Sometimes in the nova APIs
  this can be a `404` (which is wrong, but understandable given the constraints
  of the code).

* Because each handler is individually wrapped by the `wsgify`_ decorator any
  exception that is a subclass of `webob.exc.WSGIHTTPException` that is raised
  from within the handler, such as `webob.exc.HTTPBadRequest`, will be caught
  by WebOb and turned into a valid `Response`_ containing headers and body set
  by WebOb based on the information given when the exception was raised. It
  will not be seen as an exception by any of the middleware in the placement
  stack.

  In general this is a good thing, but it can lead to some confusion if, for
  example, you are trying to add some middleware that operates on exceptions.

  Other exceptions that are not from `WebOb`_ will raise outside the handlers
  where they will either be caught in the `__call__` method of the
  `PlacementHandler` app that is responsible for dispatch, or by the
  `FaultWrap` middleware.

Microversions
=============

.. TODO(cdent) fill in with how and why of microversions, maybe move some content
               from placement.rst, but include references to the decorators and
               other vailable methods.

Adding a New Handler
====================

.. TODO(cdent) short step by step summary of adding a new endpoint

Testing
=======

.. TODO(cdent) a bit about gabbi tests and unit tests: how to use
               and when to use what

Futures
=======

.. TODO(cdent) extraction to own thing plans

.. _WSGI: https://www.python.org/dev/peps/pep-3333/
.. _versioned objects: http://docs.openstack.org/developer/oslo.versionedobjects/
.. _wsgify: http://docs.webob.org/en/latest/api/dec.html
.. _WebOb: http://docs.webob.org/en/latest/
.. _Request: http://docs.webob.org/en/latest/reference.html#request
.. _Response: http://docs.webob.org/en/latest/#response
