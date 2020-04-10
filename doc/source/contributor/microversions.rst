API Microversions
=================

Background
----------

Nova uses a framework we call 'API Microversions' for allowing changes
to the API while preserving backward compatibility. The basic idea is
that a user has to explicitly ask for their request to be treated with
a particular version of the API. So breaking changes can be added to
the API without breaking users who don't specifically ask for it. This
is done with an HTTP header ``OpenStack-API-Version`` which has as its
value a string containing the name of the service, ``compute``, and a
monotonically increasing semantic version number starting from ``2.1``.
The full form of the header takes the form::

    OpenStack-API-Version: compute 2.1

If a user makes a request without specifying a version, they will get
the ``DEFAULT_API_VERSION`` as defined in
``nova/api/openstack/wsgi.py``.  This value is currently ``2.1`` and
is expected to remain so for quite a long time.

There is a special value ``latest`` which can be specified, which will
allow a client to always receive the most recent version of API
responses from the server.

.. warning:: The ``latest`` value is mostly meant for integration testing and
  would be dangerous to rely on in client code since Nova microversions are not
  following semver and therefore backward compatibility is not guaranteed.
  Clients, like python-novaclient, should always require a specific
  microversion but limit what is acceptable to the version range that it
  understands at the time.

.. warning:: To maintain compatibility, an earlier form of the microversion
   header is acceptable. It takes the form::

        X-OpenStack-Nova-API-Version: 2.1

   This form will continue to be supported until the ``DEFAULT_API_VERSION``
   is raised to version ``2.27`` or higher.

   Clients accessing deployments of the Nova API which are not yet
   providing microversion ``2.27`` must use the older form.

For full details please read the `Kilo spec for microversions
<https://opendev.org/openstack/nova-specs/src/branch/master/specs/kilo/implemented/api-microversions.rst>`_
and `Microversion Specification
<http://specs.openstack.org/openstack/api-wg/guidelines/microversion_specification.html>`_.

When do I need a new Microversion?
----------------------------------

A microversion is needed when the contract to the user is
changed. The user contract covers many kinds of information such as:

- the Request

  - the list of resource urls which exist on the server

    Example: adding a new servers/{ID}/foo which didn't exist in a
    previous version of the code

  - the list of query parameters that are valid on urls

    Example: adding a new parameter ``is_yellow`` servers/{ID}?is_yellow=True

  - the list of query parameter values for non free form fields

    Example: parameter filter_by takes a small set of constants/enums "A",
    "B", "C". Adding support for new enum "D".

  - new headers accepted on a request

  - the list of attributes and data structures accepted.

    Example: adding a new attribute 'locked': True/False to the request body

    However, the attribute ``os.scheduler_hints`` of the "create a server" API
    is an exception to this. A new scheduler which adds a new attribute
    to ``os:scheduler_hints`` doesn't require a new microversion, because
    available schedulers depend on cloud environments, and we accept customized
    schedulers as a rule.

- the Response

  - the list of attributes and data structures returned

    Example: adding a new attribute 'locked': True/False to the output
    of servers/{ID}

  - the allowed values of non free form fields

    Example: adding a new allowed ``status`` to servers/{ID}

  - the list of status codes allowed for a particular request

    Example: an API previously could return 200, 400, 403, 404 and the
    change would make the API now also be allowed to return 409.

    See [#f2]_ for the 400, 403, 404 and 415 cases.

  - changing a status code on a particular response

    Example: changing the return code of an API from 501 to 400.

    .. note:: Fixing a bug so that a 400+ code is returned rather than a 500 or
      503 does not require a microversion change. It's assumed that clients are
      not expected to handle a 500 or 503 response and therefore should not
      need to opt-in to microversion changes that fixes a 500 or 503 response
      from happening.
      According to the OpenStack API Working Group, a
      **500 Internal Server Error** should **not** be returned to the user for
      failures due to user error that can be fixed by changing the request on
      the client side. See [#f1]_.

  - new headers returned on a response

The following flow chart attempts to walk through the process of "do
we need a microversion".


.. graphviz::

   digraph states {

    label="Do I need a microversion?"

    silent_fail[shape="diamond", style="", group=g1, label="Did we silently
   fail to do what is asked?"];
    ret_500[shape="diamond", style="", group=g1, label="Did we return a 500
   before?"];
    new_error[shape="diamond", style="", group=g1, label="Are we changing what
    status code is returned?"];
    new_attr[shape="diamond", style="", group=g1, label="Did we add or remove an
    attribute to a payload?"];
    new_param[shape="diamond", style="", group=g1, label="Did we add or remove
    an accepted query string parameter or value?"];
    new_resource[shape="diamond", style="", group=g1, label="Did we add or remove a
   resource url?"];


   no[shape="box", style=rounded, label="No microversion needed"];
   yes[shape="box", style=rounded, label="Yes, you need a microversion"];
   no2[shape="box", style=rounded, label="No microversion needed, it's
   a bug"];

   silent_fail -> ret_500[label=" no"];
   silent_fail -> no2[label="yes"];

    ret_500 -> no2[label="yes [1]"];
    ret_500 -> new_error[label=" no"];

    new_error -> new_attr[label=" no"];
    new_error -> yes[label="yes"];

    new_attr -> new_param[label=" no"];
    new_attr -> yes[label="yes"];

    new_param -> new_resource[label=" no"];
    new_param -> yes[label="yes"];

    new_resource -> no[label=" no"];
    new_resource -> yes[label="yes"];

   {rank=same; yes new_attr}
   {rank=same; no2 ret_500}
   {rank=min; silent_fail}
   }


**Footnotes**

.. [#f1] When fixing 500 errors that previously caused stack traces, try
  to map the new error into the existing set of errors that API call
  could previously return (400 if nothing else is appropriate). Changing
  the set of allowed status codes from a request is changing the
  contract, and should be part of a microversion (except in [#f2]_).

  The reason why we are so strict on contract is that we'd like
  application writers to be able to know, for sure, what the contract is
  at every microversion in Nova. If they do not, they will need to write
  conditional code in their application to handle ambiguities.

  When in doubt, consider application authors. If it would work with no
  client side changes on both Nova versions, you probably don't need a
  microversion. If, on the other hand, there is any ambiguity, a
  microversion is probably needed.

.. [#f2] The exception to not needing a microversion when returning a
  previously unspecified error code is the 400, 403, 404 and 415 cases. This is
  considered OK to return even if previously unspecified in the code since
  it's implied given keystone authentication can fail with a 403 and API
  validation can fail with a 400 for invalid json request body. Request to
  url/resource that does not exist always fails with 404. Invalid content types
  are handled before API methods are called which results in a 415.

    .. note:: When in doubt about whether or not a microversion is required
        for changing an error response code, consult the `Nova API subteam`_.

.. _Nova API subteam: https://wiki.openstack.org/wiki/Meetings/NovaAPI


When a microversion is not needed
---------------------------------

A microversion is not needed in the following situation:

- the response

  - Changing the error message without changing the response code
    does not require a new microversion.

  - Removing an inapplicable HTTP header, for example, suppose the Retry-After
    HTTP header is being returned with a 4xx code. This header should only be
    returned with a 503 or 3xx response, so it may be removed without bumping
    the microversion.

  - An obvious regression bug in an admin-only API where the bug can still
    be fixed upstream on active stable branches. Admin-only APIs are less of
    a concern for interoperability and generally a regression in behavior can
    be dealt with as a bug fix when the documentation clearly shows the API
    behavior was unexpectedly regressed. See [#f3]_ for an example. Intentional
    behavior changes to an admin-only API *do* require a microversion, like the
    :ref:`2.53 microversion <2.53-microversion>` for example.

**Footnotes**

.. [#f3] https://review.opendev.org/#/c/523194/

In Code
-------

In ``nova/api/openstack/wsgi.py`` we define an ``@api_version`` decorator
which is intended to be used on top-level Controller methods. It is
not appropriate for lower-level methods. Some examples:

Adding a new API method
~~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("2.4")
    def my_api_method(self, req, id):
        ....

This method would only be available if the caller had specified an
``OpenStack-API-Version`` of >= ``2.4``. If they had specified a
lower version (or not specified it and received the default of ``2.1``)
the server would respond with ``HTTP/404``.

Removing an API method
~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("2.1", "2.4")
    def my_api_method(self, req, id):
        ....

This method would only be available if the caller had specified an
``OpenStack-API-Version`` of <= ``2.4``. If ``2.5`` or later
is specified the server will respond with ``HTTP/404``.

Changing a method's behavior
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("2.1", "2.3")
    def my_api_method(self, req, id):
        .... method_1 ...

    @wsgi.Controller.api_version("2.4")  # noqa
    def my_api_method(self, req, id):
        .... method_2 ...

If a caller specified ``2.1``, ``2.2`` or ``2.3`` (or received the
default of ``2.1``) they would see the result from ``method_1``,
``2.4`` or later ``method_2``.

It is vital that the two methods have the same name, so the second of
them will need ``# noqa`` to avoid failing flake8's ``F811`` rule. The
two methods may be different in any kind of semantics (schema
validation, return values, response codes, etc)

A change in schema only
~~~~~~~~~~~~~~~~~~~~~~~

If there is no change to the method, only to the schema that is used for
validation, you can add a version range to the ``validation.schema``
decorator::

    @wsgi.Controller.api_version("2.1")
    @validation.schema(dummy_schema.dummy, "2.3", "2.8")
    @validation.schema(dummy_schema.dummy2, "2.9")
    def update(self, req, id, body):
        ....

This method will be available from version ``2.1``, validated according to
``dummy_schema.dummy`` from ``2.3`` to ``2.8``, and validated according to
``dummy_schema.dummy2`` from ``2.9`` onward.


When not using decorators
~~~~~~~~~~~~~~~~~~~~~~~~~

When you don't want to use the ``@api_version`` decorator on a method
or you want to change behavior within a method (say it leads to
simpler or simply a lot less code) you can directly test for the
requested version with a method as long as you have access to the api
request object (commonly called ``req``). Every API method has an
api_version_request object attached to the req object and that can be
used to modify behavior based on its value::

    def index(self, req):
        <common code>

        req_version = req.api_version_request
        req1_min = api_version_request.APIVersionRequest("2.1")
        req1_max = api_version_request.APIVersionRequest("2.5")
        req2_min = api_version_request.APIVersionRequest("2.6")
        req2_max = api_version_request.APIVersionRequest("2.10")

        if req_version.matches(req1_min, req1_max):
            ....stuff....
        elif req_version.matches(req2min, req2_max):
            ....other stuff....
        elif req_version > api_version_request.APIVersionRequest("2.10"):
            ....more stuff.....

        <common code>

The first argument to the matches method is the minimum acceptable version
and the second is maximum acceptable version. A specified version can be null::

    null_version = APIVersionRequest()

If the minimum version specified is null then there is no restriction on
the minimum version, and likewise if the maximum version is null there
is no restriction the maximum version. Alternatively a one sided comparison
can be used as in the example above.

Other necessary changes
-----------------------

If you are adding a patch which adds a new microversion, it is
necessary to add changes to other places which describe your change:

* Update ``REST_API_VERSION_HISTORY`` in
  ``nova/api/openstack/api_version_request.py``

* Update ``_MAX_API_VERSION`` in
  ``nova/api/openstack/api_version_request.py``

* Add a verbose description to
  ``nova/api/openstack/compute/rest_api_version_history.rst``.

* Add a :doc:`release note </contributor/releasenotes>` with a ``features``
  section announcing the new or changed feature and the microversion.

* Update the expected versions in affected tests, for example in
  ``nova/tests/unit/api/openstack/compute/test_versions.py``.

* Update the get versions api sample file:
  ``doc/api_samples/versions/versions-get-resp.json`` and
  ``doc/api_samples/versions/v21-version-get-resp.json``.

* Make a new commit to python-novaclient and update corresponding
  files to enable the newly added microversion API.
  See :python-novaclient-doc:`Adding support for a new microversion
  <contributor/microversions>` in python-novaclient for more details.

* If the microversion changes the response schema, a new schema and test for
  the microversion must be added to Tempest.

* If applicable, add Functional sample tests under
  ``nova/tests/functional/api_sample_tests``. Also, add JSON examples to
  ``doc/api_samples`` directory which can be generated automatically via tox
  env ``api-samples`` or run test with env var ``GENERATE_SAMPLES`` True.

* Update the `API Reference`_ documentation as appropriate.  The source is
  located under `api-ref/source/`.

* If the microversion changes servers related APIs, update the
  ``api-guide/source/server_concepts.rst`` accordingly.

.. _API Reference: https://docs.openstack.org/api-ref/compute/

Allocating a microversion
-------------------------

If you are adding a patch which adds a new microversion, it is
necessary to allocate the next microversion number. Except under
extremely unusual circumstances and this would have been mentioned in
the nova spec for the change, the minor number of ``_MAX_API_VERSION``
will be incremented. This will also be the new microversion number for
the API change.

It is possible that multiple microversion patches would be proposed in
parallel and the microversions would conflict between patches.  This
will cause a merge conflict. We don't reserve a microversion for each
patch in advance as we don't know the final merge order. Developers
may need over time to rebase their patch calculating a new version
number as above based on the updated value of ``_MAX_API_VERSION``.

Testing Microversioned API Methods
----------------------------------

Testing a microversioned API method is very similar to a normal controller
method test, you just need to add the ``OpenStack-API-Version``
header, for example::

    req = fakes.HTTPRequest.blank('/testable/url/endpoint')
    req.headers = {'OpenStack-API-Version': 'compute 2.28'}
    req.api_version_request = api_version.APIVersionRequest('2.6')

    controller = controller.TestableController()

    res = controller.index(req)
    ... assertions about the response ...

For many examples of testing, the canonical examples are in
``nova/tests/unit/api/openstack/compute/test_microversions.py``.
