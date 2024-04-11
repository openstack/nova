Extending the API
=================

.. note::

    This document provides general background information on how one can extend
    the REST API in nova. For information on the microversion support including
    how to add new microversions, see :doc:`/contributor/microversions`. For
    information on how to use the API, refer to the `API guide`__ and `API
    reference guide`__.

    .. __: https://docs.openstack.org/api-guide/compute/
    .. __: https://docs.openstack.org/api-ref/compute/

Nova's API is a mostly RESTful API. REST stands for *Representational State
Transfer* and provides an architecture "style" for distributed systems using
HTTP for transport. Figure out a way to express your request and response in
terms of resources that are being created, modified, read, or destroyed.

Nova has v2.1 API frameworks which supports microversions.
This document covers how to add API for the v2.1 API framework. A
:doc:`microversions-specific document <microversions>` covers the details
around what is required for the microversions part.

The v2.1 API framework is under ``nova/api`` and each API is implemented in
``nova/api/openstack/compute``.

.. note::

    Any change to the Nova API to be merged will first require a spec be
    approved first.
    See `here <https://opendev.org/openstack/nova-specs>`_ for the appropriate
    repository.
    For guidance on the design of the API please refer to the `OpenStack API WG
    <https://wiki.openstack.org/wiki/API_Working_Group>`_


Basic API Controller
--------------------

API controller includes the implementation of API methods for a resource.

A very basic controller of a v2.1 API:

.. code-block:: python

    """Basic Controller"""

    from nova.api.openstack.compute.schemas import xyz
    from nova.api.openstack import extensions
    from nova.api.openstack import wsgi
    from nova.api import validation

    class BasicController(wsgi.Controller):

        # Define support for GET on a collection
        def index(self, req):
            data = {'param': 'val'}
            return data

        # Define support for POST on a collection
        @extensions.expected_errors((400, 409))
        @validation.schema(xyz.create)
        @wsgi.response(201)
        def create(self, req, body):
            write_body_here = ok
            return response_body

        # Defining support for other RESTFul methods based on resource.

        # ...


See `servers.py <https://opendev.org/openstack/nova/src/branch/master/nova/api/openstack/compute/servers.py>`_ for ref.

All of the controller modules should live in the ``nova/api/openstack/compute`` directory.

URL Mapping to API
~~~~~~~~~~~~~~~~~~

The URL mapping is based on the plain list which routes the API request to
appropriate controller and method. Each API needs to add its route information
in ``nova/api/openstack/compute/routes.py``.

A basic skeleton of URL mapping in ``routers.py``:

.. code-block:: python

    """URL Mapping Router List"""

    import functools

    import nova.api.openstack
    from nova.api.openstack.compute import basic_api

    # Create a controller object
    basic_controller = functools.partial(
        _create_controller, basic_api.BasicController, [], [],
    )

    # Routing list structure:
    # (
    #     ('Route path': {
    #         'HTTP method: [
    #             'Controller',
    #             'The method of controller is used to handle this route'
    #         ],
    #         ...
    #     }),
    #     ...
    # )
    ROUTE_LIST = (
        # ...
        ('/basic', {
            'GET': [basic_controller, 'index'],
            'POST': [basic_controller, 'create']
        }),
        # ...
    )

Complete routing list can be found in `routes.py
<https://opendev.org/openstack/nova/src/branch/master/nova/api/openstack/compute/routes.py>`_.

Policy
~~~~~~

For more info about policy, see :doc:`policies </configuration/policy>`,
Also look at the ``context.can(...)`` call in existing API controllers.

Modularity
~~~~~~~~~~

The Nova REST API is separated into different controllers in the directory
``nova/api/openstack/compute/``.

Because microversions are supported in the Nova REST API, the API can be
extended without any new controller. But for code readability, the Nova REST API
code still needs modularity. Here are rules for how to separate modules:

* You are adding a new resource
  The new resource should be in standalone module. There isn't any reason to
  put different resources in a single module.

* Add sub-resource for existing resource
  To prevent an existing resource module becoming over-inflated, the
  sub-resource should be implemented in a separate module.

* Add extended attributes for existing resource
  In normally, the extended attributes is part of existing resource's data
  model too. So this can be added into existing resource module directly and
  lightly.
  To avoid namespace complexity, we should avoid to add extended attributes
  in existing extended models. New extended attributes needn't any namespace
  prefix anymore.

Validation
~~~~~~~~~~

.. versionchanged:: 2024.2 (Dalmatian)

   Added response body schema validation, to complement request body and
   request query string validation.

The v2.1 API uses JSON Schema for validation. Before 2024.2 (Dalmatian), this
was used for request body and request query string validation. Since then, it
is also used for response body validation. The request body and query string
validation is used at runtime and is non-optional, while the response body
validation is only used for test and documentation purposes and should not be
enabled at runtime.

Validation is added for a given resource and method using decorators provided
in ``nova.api.validation`` while the schemas themselves can be found in
``nova.api.openstack.compute.schemas``. We use unit tests to ensure all method
are decorated correctly and schemas are defined. The decorators accept optional
``min_version`` and ``max_version`` arguments, allowing you to define different
schemas for different microversions. For example:

.. code-block:: python

   @validation.schema(schema.update, '2.1', '2.77')
   @validation.schema(schema.update_v278, '2.78')
   @validation.query_schema(schema.update_query)
   @validation.response_body_schema(schema.update_response, '2.1', '2.6')
   @validation.response_body_schema(schema.update_response_v27, '2.7', '2.77')
   @validation.response_body_schema(schema.update_response_v278, '2.78')
   def update(self, req, id, body):
       ...

In addition to the JSON Schema validation decorator, we provide decorators for
indicating expected response and error codes, indicating removed APIs, and
indicating "action" APIs. These can be found in ``nova.api.openstack.wsgi``.
For example, to indicate that an API can return ``400 (Bad Request)``, ``404
(Not Found)``, or ``409 (Conflict)`` error codes but returns ``200 (OK)`` in
the success case:

.. code-block:: python

   @wsgi.expected_errors((400, 404, 409))
   @wsgi.response(201)
   def update(self, req, id, body):
       ...

To define a new action, ``foo``, for a given resource:

.. code-block:: python

   @wsgi.action('foo')
   def update(self, req, id, body):
       ...

To indicate that an API has been removed and will now return ``410 (Gone)`` for
all requests:

.. code-block:: python

   @wsgi.removed('30.0.0', 'This API was removed because...')
   def update(self, req, id, body):
       ...

Unit Tests
----------

Unit tests for the API can be found under path
``nova/tests/unit/api/openstack/compute/``. Unit tests for the
API are generally negative scenario tests, because the positive
scenarios are tested with functional API samples tests.

Negative tests would include such things as:

* Request schema validation failures, for both the request body and query
  parameters
* ``HTTPNotFound`` or other >=400 response code failures


Functional tests and API Samples
--------------------------------

All functional API changes, including new microversions - especially if there
are new request or response parameters, should have new functional API samples
tests.

The API samples tests are made of two parts:

* The API sample for the reference docs. These are found under path
  ``doc/api_samples/``. There is typically one directory per API controller
  with subdirectories per microversion for that API controller. The unversioned
  samples are used for the base v2.0 / v2.1 APIs.

* Corresponding API sample templates found under path
  ``nova/tests/functional/api_sample_tests/api_samples``. These have a similar
  structure to the API reference docs samples, except the format of the sample
  can include substitution variables filled in by the tests where necessary,
  for example, to substitute things that change per test run, like a server
  UUID.

The actual functional tests are found under path
``nova/tests/functional/api_sample_tests/``. Most, if not all, API samples
tests extend the ``ApiSampleTestBaseV21`` class which extends
``ApiSampleTestBase``. These base classes provide the framework for making
a request using an API reference doc sample and validating the response using
the corresponding template file, along with any variable substitutions that
need to be made.

Note that it is possible to automatically generate the API reference doc
samples using the templates by simply running the tests using
``tox -e api-samples``. This relies, of course, upon the test and templates
being correct for the test to pass, which may take some iteration.

In general, if you are adding a new microversion to an existing API controller,
it is easiest to simply copy an existing test and modify it for the new
microversion and the new samples/templates.

The functional API samples tests are not the simplest thing in the world to
get used to and it can be very frustrating at times when they fail in not
obvious ways. If you need help debugging a functional API sample test failure,
feel free to post your work-in-progress change for review and ask for help in
the ``openstack-nova`` OFTC IRC channel.


Documentation
-------------

All API changes must also include updates to the compute API reference,
which can be found under path ``api-ref/source/``.

Things to consider here include:

* Adding new request and/or response parameters with a new microversion
* Marking existing parameters as deprecated in a new microversion

More information on the compute API reference format and conventions can
be found in the :doc:`/contributor/api-ref-guideline`.

For more detailed documentation of certain aspects of the API, consider
writing something into the compute API guide found under path
``api-guide/source/``.


Deprecating APIs
----------------

Compute REST API routes may be deprecated by capping a method or functionality
using microversions. For example, the
:ref:`2.36 microversion <2.36 microversion>` deprecated several compute REST
API routes which only worked when using the since-removed ``nova-network``
service or are proxies to other external services like cinder, neutron, etc.

The point of deprecating with microversions is users can still get the same
functionality at a lower microversion but there is at least some way to signal
to users that they should stop using the REST API.

The general steps for deprecating a REST API are:

* Set a maximum allowed microversion for the route. Requests beyond that
  microversion on that route will result in a ``404 (Not Found)`` error.

* Update the Compute API reference documentation to indicate the route is
  deprecated and move it to the bottom of the list with the other deprecated
  APIs.

* Deprecate, and eventually remove, related CLI / SDK functionality in other
  projects like *python-novaclient*.


Removing deprecated APIs
------------------------

Nova tries to maintain backward compatibility with all REST APIs as much as
possible, but when enough time has lapsed, there are few (if any) users or
there are supported alternatives, the underlying service code that supports a
deprecated REST API, like in the case of ``nova-network``, is removed and the
REST API must also be effectively removed.

The general steps for removing support for a deprecated REST API are:

* The `route mapping`_ will remain but all methods will return a
  ``410 (Gone)`` error response. This is slightly different to the
  ``404 (Not Found)`` error response a user will get for trying to use a
  microversion that does not support a deprecated API. 410 means the resource
  is gone and not coming back, which is more appropriate when the API is
  fully removed and will not work at any microversion.

* Related configuration options, policy rules, and schema validation are
  removed.

* The API reference documentation should be updated to move the documentation
  for the removed API to the `Obsolete APIs`_ section and mention in which
  release the API was removed.

* Unit tests can be removed.

* API sample functional tests can be changed to assert the 410 response
  behavior, but can otherwise be mostly gutted. Related \*.tpl files for the
  API sample functional tests can be deleted since they will not be used.

* An "upgrade" :doc:`release note <releasenotes>` should be added to mention
  the REST API routes that were removed along with any related configuration
  options that were also removed.

Here is an example of the above steps: https://review.opendev.org/567682/

.. _route mapping: https://opendev.org/openstack/nova/src/branch/master/nova/api/openstack/compute/routes.py
.. _Obsolete APIs: https://docs.openstack.org/api-ref/compute/#obsolete-apis
