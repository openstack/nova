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

The Nova project introduced the :doc:`placement service </user/placement>` as
part of the Newton release. The service provides an HTTP API to manage
inventories of different classes of resources, such as disk or virtual cpus,
made available by entities called resource providers. Information provided
through the placement API is intended to enable more effective accounting of
resources in an OpenStack deployment and better scheduling of various entities
in the cloud.

The document serves to explain the architecture of the system and to provide
some guidance on how to maintain and extend the code. For more detail on why
the system was created and how it does its job see :doc:`/user/placement`.

Big Picture
===========

The placement service is straightforward: It is a `WSGI`_ application that
sends and receives JSON, using an RDBMS (usually MySQL) for persistence.
As state is managed solely in the DB, scaling the placement service is done by
increasing the number of WSGI application instances and scaling the RDBMS using
traditional database scaling techniques.

For sake of consistency and because there was initially intent to make the
entities in the placement service available over RPC,
:oslo.versionedobjects-doc:`versioned objects <>` are used to provide the
interface between the HTTP application layer and the SQLAlchemy-driven
persistence layer. Even without RPC, these objects provide useful structuring
and separation of the code.

Though the placement service doesn't aspire to be a `microservice` it does
aspire to continue to be small and minimally complex. This means a relatively
small amount of middleware that is not configurable, and a limited number of
exposed resources where any given resource is represented by one (and only
one) URL that expresses a noun that is a member of the system. Adding
additional resources should be considered a significant change requiring robust
review from many stakeholders.

The set of HTTP resources represents a concise and constrained grammar for
expressing the management of resource providers, inventories, resource classes,
traits, and allocations. If a solution is initially designed to need more
resources or a more complex grammar that may be a sign that we need to give our
goals greater scrutiny. Is there a way to do what we want with what we have
already?  Can some other service help? Is a new collaborating service required?

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
application, using a subclass of the `wsgify`_  method from `WebOb`_ to provide
a `Request`_ object that provides convenience methods for accessing request
headers, bodies, and query parameters and for generating responses. In the
placement API these mini-applications are called `handlers`. The `wsgify`
subclass is provided in `nova.api.openstack.placement.wsgi_wrapper` as
`PlacementWsgify`. It is used to make sure that JSON formatted error responses
are structured according to the API-WG `errors`_ guideline.

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

* Because each handler is individually wrapped by the `PlacementWsgify`
  decorator any exception that is a subclass of `webob.exc.WSGIHTTPException`
  that is raised from within the handler, such as `webob.exc.HTTPBadRequest`,
  will be caught by WebOb and turned into a valid `Response`_ containing
  headers and body set by WebOb based on the information given when the
  exception was raised. It will not be seen as an exception by any of the
  middleware in the placement stack.

  In general this is a good thing, but it can lead to some confusion if, for
  example, you are trying to add some middleware that operates on exceptions.

  Other exceptions that are not from `WebOb`_ will raise outside the handlers
  where they will either be caught in the `__call__` method of the
  `PlacementHandler` app that is responsible for dispatch, or by the
  `FaultWrap` middleware.

Microversions
=============

The placement API makes use of `microversions`_ to allow the release of new
features on an opt in basis. See :doc:`/user/placement` for an up to date
history of the available microversions.

The rules around when a microversion is needed are the same as for the
:doc:`compute API </contributor/microversions>`. When adding a new microversion
there are a few bits of required housekeeping that must be done in the code:

* Update the ``VERSIONS`` list in
  ``nova/api/openstack/placement/microversion.py`` to indicate the new
  microversion and give a very brief summary of the added feature.
* Update ``nova/api/openstack/placement/rest_api_version_history.rst``
  to add a more detailed section describing the new microversion.
* Add a :reno-doc:`release note <>` with a ``features`` section announcing the
  new or changed feature and the microversion.
* If the ``version_handler`` decorator (see below) has been used,
  increment ``TOTAL_VERSIONED_METHODS`` in
  ``nova/tests/unit/api/openstack/placement/test_microversion.py``.
  This provides a confirmatory check just to make sure you're paying
  attention and as a helpful reminder to do the other things in this
  list.
* Include functional gabbi tests as appropriate (see `Using Gabbi`_).  At the
  least, update the ``latest microversion`` test in
  ``nova/tests/functional/api/openstack/placement/gabbits/microversion.yaml``.
* Update the `API Reference`_ documentation as appropriate.  The source is
  located under `placement-api-ref/source/`.

In the placement API, microversions only use the modern form of the
version header::

    OpenStack-API-Version: placement 1.2

If a valid microversion is present in a request it will be placed,
as a ``Version`` object, into the WSGI environment with the
``placement.microversion`` key. Often, accessing this in handler
code directly (to control branching) is the most explicit and
granular way to have different behavior per microversion. A
``Version`` instance can be treated as a tuple of two ints and
compared as such or there is a ``matches`` method.

A ``version_handler`` decorator is also available. It makes it possible to have
multiple different handler methods of the same (fully-qualified by package)
name, each available for a different microversion window.  If a request wants a
microversion that's not available, a defined status code is returned (usually
``404`` or ``405``). There is a unit test in place which will fail if there are
version intersections.

Adding a New Handler
====================

Adding a new URL or a new method (e.g, ``PATCH``) to an existing URL
requires adding a new handler function. In either case a new microversion and
release note is required. When adding an entirely new route a request for a
lower microversion should return a ``404``. When adding a new method to an
existing URL a request for a lower microversion should return a ``405``.

In either case, the ``ROUTE_DECLARATIONS`` dictionary in the
`nova.api.openstack.placement.handler` module should be updated to point to a
function within a module that contains handlers for the type of entity
identified by the URL. Collection and individual entity handlers of the same
type should be in the same module.

As mentioned above, the handler function should be decorated with
``@wsgi_wrapper.PlacementWsgify``, take a single argument ``req`` which is a
WebOb `Request`_ object, and return a WebOb `Response`_.

For ``PUT`` and ``POST`` methods, request bodies are expected to be JSON
based on a content-type of ``application/json``. This may be enforced by using
a decorator: ``@util.require_content('application/json')``. If the body is not
`JSON`, a ``415`` response status is returned.

Response bodies are usually `JSON`. A handler can check the `Accept` header
provided in a request using another decorator:
``@util.check_accept('application/json')``. If the header does not allow
`JSON`, a ``406`` response status is returned.

If a hander returns a response body, a ``Last-Modified`` header should be
included with the response. If the entity or entities in the response body
are directly associated with an object (or objects, in the case of a
collection response) that has an ``updated_at`` (or ``created_at``)
field, that field's value can be used as the value of the header (WebOb will
take care of turning the datetime object into a string timestamp). A
``util.pick_last_modified`` is available to help choose the most recent
last-modified when traversing a collection of entities.

If there is no directly associated object (for example, the output is the
composite of several objects) then the ``Last-Modified`` time should be
``timeutils.utcnow(with_timezone=True)`` (the timezone must be set in order
to be a valid HTTP timestamp). For example, the response__ to
``GET /allocation_candidates`` should have a last-modified header of now
because it is composed from queries against many different database entities,
presents a mixture of result types (allocation requests and provider
summaries), and has a view of the system that is only meaningful *now*.

__ https://developer.openstack.org/api-ref/placement/#list-allocation-candidates

If a ``Last-Modified`` header is set, then a ``Cache-Control`` header with a
value of ``no-cache`` must be set as well. This is to avoid user-agents
inadvertently caching the responses.

`JSON` sent in a request should be validated against a JSON Schema. A
``util.extract_json`` method is available. This takes a request body and a
schema. If multiple schema are used for different microversions of the same
request, the caller is responsible for selecting the right one before calling
``extract_json``.

When a handler needs to read or write the data store it should use methods on
the objects found in the
`nova.api.openstack.placement.objects.resource_provider` package. Doing so
requires a context which is provided to the handler method via the WSGI
environment. It can be retrieved as follows::

    context = req.environ['placement.context']

.. note:: If your change requires new methods or new objects in the
          `resource_provider` package, after you've made sure that you really
          do need those new methods or objects (you may not!) make those
          changes in a patch that is separate from and prior to the HTTP API
          change.

If a handler needs to return an error response, with the advent of `Placement
API Error Handling`_, it is possible to include a code in the JSON error
response.  This can be used to distinguish different errors with the same HTTP
response status code (a common case is a generation conflict versus an
inventory in use conflict). Error codes are simple namespaced strings (e.g.,
``placement.inventory.inuse``) for which symbols are maintained in
``nova.api.openstack.placement.errors``. Adding a symbol to a response is done
by using the ``comment`` kwarg to a WebOb exception, like this::

    except exception.InventoryInUse as exc:
        raise webob.exc.HTTPConflict(
            _('update conflict: %(error)s') % {'error': exc},
            comment=errors.INVENTORY_INUSE)

Code that adds newly raised exceptions should include an error code. Find
additional guidelines on use in the docs for
``nova.api.openstack.placement.errors``.

Testing of handler code is described in the next section.

Testing
=======

Most of the handler code in the placement API is tested using `gabbi`_. Some
utility code is tested with unit tests found in
`nova/tests/unit/api/openstack/placement/`. The back-end objects are tested
with a combination of unit and functional tests found in
``nova/tests/unit/api/openstack/placement/objects/test_resource_provider.py``
and `nova/tests/functional/api/openstack/placement/db`. Adding unit and
non-gabbi functional tests is done in the same way as other aspects of nova.

When writing tests for handler code (that is, the code found in
``nova/api/openstack/placement/handlers``) a good rule of thumb is that if you
feel like there needs to be a unit test for some of the code in the handler,
that is a good sign that the piece of code should be extracted to a separate
method. That method should be independent of the handler method itself (the one
decorated by the ``wsgify`` method) and testable as a unit, without mocks if
possible. If the extracted method is useful for multiple resources consider
putting it in the ``util`` package.

As a general guide, handler code should be relatively short and where there are
conditionals and branching, they should be reachable via the gabbi functional
tests. This is merely a design goal, not a strict constraint.

Using Gabbi
-----------

Gabbi was developed in the `telemetry`_ project to provide a declarative way to
test HTTP APIs that preserves visibility of both the request and response of
the HTTP interaction. Tests are written in YAML files where each file is an
ordered suite of tests. Fixtures (such as a database) are set up and torn down
at the beginning and end of each file, not each test. JSON response bodies can
be evaluated with `JSONPath`_. The placement WSGI
application is run via `wsgi-intercept`_, meaning that real HTTP requests are
being made over a file handle that appears to Python to be a socket.

In the placement API the YAML files (aka "gabbits") can be found in
``nova/tests/functional/api/openstack/placement/gabbits``. Fixture definitions
are in ``nova/tests/functional/api/openstack/placement/fixtures/gabbits.py``.
Tests are frequently grouped by handler name (e.g., ``resource-provider.yaml``
and ``inventory.yaml``). This is not a requirement and as we increase the
number of tests it makes sense to have more YAML files with fewer tests,
divided up by the arc of API interaction that they test.

The gabbi tests are integrated into the functional tox target, loaded via
``nova/tests/functional/api/openstack/placement/test_placement_api.py``. If you
want to run just the gabbi tests one way to do so is::

    tox -efunctional test_placement_api

If you want to run just one yaml file (in this example ``inventory.yaml``)::

    tox -efunctional placement_api.inventory

It is also possible to run just one test from within one file. When you do this
every test prior to the one you asked for will also be run. This is because
the YAML represents a sequence of dependent requests. Select the test by using
the name in the yaml file, replacing space with ``_``::

    tox -efunctional placement_api.inventory_post_new_ipv4_address_inventory

.. note:: ``tox.ini`` in the nova repository is configured by a ``group_regex``
          so that each gabbi YAML is considered a group. Thus, all tests in the
          file will be run in the same process when running stestr concurrently
          (the default).

Writing More Gabbi Tests
------------------------

The docs for `gabbi`_ try to be complete and explain the `syntax`_ in some
depth. Where something is missing or confusing, please log a `bug`_.

While it is possible to test all aspects of a response (all the response
headers, the status code, every attribute in a JSON structure) in one single
test, doing so will likely make the test harder to read and will certainly make
debugging more challenging. If there are multiple things that need to be
asserted, making multiple requests is reasonable. Since database set up is only
happening once per file (instead of once per test) and since there's no TCP
overhead, the tests run quickly.

While `fixtures`_ can be used to establish entities that are required for
tests, creating those entities via the HTTP API results in tests which are more
descriptive. For example the ``inventory.yaml`` file creates the resource
provider to which it will then add inventory. This makes it easy to explore a
sequence of interactions and a variety of responses with the tests:

* create a resource provider
* confirm it has empty inventory
* add inventory to the resource provider (in a few different ways)
* confirm the resource provider now has inventory
* modify the inventory
* delete the inventory
* confirm the resource provider now has empty inventory

Nothing special is required to add a new set of tests: create a YAML file with
a unique name in the same directory as the others. The other files can provide
examples. Gabbi can provide a useful way of doing test driven development of a
new handler: create a YAML file that describes the desired URLs and behavior
and write the code to make it pass.

It's also possible to use gabbi against a running placement service, for
example in devstack. See `gabbi-run`_ to get started.

Futures
=======

Since before it was created there has been a long term goal for the placement
service to be extracted to its own repository and operate as its own
independent service. There are many reasons for this, but two main ones are:

* Multiple projects, not just nova, will eventually need to manage resource
  providers using the placement API.
* A separate service helps to maintain and preserve a strong contract between
  the placement service and the consumers of the service.

To lessen the pain of the eventual extraction of placement the service has been
developed in a way to limit dependency on the rest of the nova codebase and be
self-contained:

* Most code is in `nova/api/openstack/placement`.
* Database query code is kept within the objects in
  `nova/api/openstack/placement/objects`.
* The methods on the objects are not remotable, as the only intended caller is
  the placement API code.

There are some exceptions to the self-contained rule (which are actively being
addressed to prepare for the extraction):

* Some of the code related to a resource class cache is within the `nova.db`
  package, while other parts are in ``nova/rc_fields.py``.
* Database models, migrations and tables are described as part of the nova api
  database. An optional configuration option,
  :oslo.config:option:`placement_database.connection`, can be set to use a
  database just for placement (based on the api database schema).
* `nova.i18n` package provides the ``_`` and related functions.
* ``nova.conf`` is used for configuration.
* Unit and functional tests depend on fixtures and other functionality in base
  classes provided by nova.

When creating new code for the placement service, please be aware of the plan
for an eventual extraction and avoid creating unnecessary interdependencies.

.. _WSGI: https://www.python.org/dev/peps/pep-3333/
.. _wsgify: http://docs.webob.org/en/latest/api/dec.html
.. _WebOb: http://docs.webob.org/en/latest/
.. _Request: http://docs.webob.org/en/latest/reference.html#request
.. _Response: http://docs.webob.org/en/latest/#response
.. _microversions: http://specs.openstack.org/openstack/api-wg/guidelines/microversion_specification.html
.. _gabbi: https://gabbi.readthedocs.io/
.. _telemetry: http://specs.openstack.org/openstack/telemetry-specs/specs/kilo/declarative-http-tests.html
.. _wsgi-intercept: http://wsgi-intercept.readthedocs.io/
.. _syntax: https://gabbi.readthedocs.io/en/latest/format.html
.. _bug: https://github.com/cdent/gabbi/issues
.. _fixtures: http://gabbi.readthedocs.io/en/latest/fixtures.html
.. _JSONPath: http://goessner.net/articles/JsonPath/
.. _gabbi-run: http://gabbi.readthedocs.io/en/latest/runner.html
.. _errors: http://specs.openstack.org/openstack/api-wg/guidelines/errors.html
.. _API Reference: https://developer.openstack.org/api-ref/placement/
.. _Placement API Error Handling: http://specs.openstack.org/openstack/nova-specs/specs/rocky/approved/placement-api-error-handling.html
