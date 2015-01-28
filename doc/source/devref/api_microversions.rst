API Microversions
=================

Background
----------

Nova uses a framework we call 'API Microversions' for allowing changes
to the API while preserving backward compatibility. The basic idea is
that a user has to explicitly ask for their request to be treated with
a particular version of the API. So breaking changes can be added to
the API without breaking users who don't specifically ask for it. This
is done with an HTTP header ``X-OpenStack-Compute-API-Version`` which
is a monotonically increasing semantic version number starting from
``2.1``.

If a user makes a request without specifying a version, they will get
the ``DEFAULT_API_VERSION`` as defined in
``nova/api/openstack/wsgi.py``.  This value is currently ``2.1`` and
is expected to remain so for quite a long time.

There is a special value ``latest`` which can be specified, which will
allow a client to always recieve the most recent version of API
responses from the server.

For full details please read the `Kilo spec for microversions
<http://git.openstack.org/cgit/openstack/nova-specs/tree/specs/kilo/approved/api-microversions.rst>`_


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
``X-OpenStack-Compute-API-Version`` of >= ``2.4``. If they had specified a
lower version (or not specified it and received the default of ``2.1``)
the server would respond with ``HTTP/404``.

Removing an API method
~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("2.1", "2.4")
    def my_api_method(self, req, id):
        ....

This method would only be available if the caller had specified an
``X-OpenStack-Compute-API-Version`` of <= ``2.4``. If ``2.5`` or later
is specified the server will respond with ``HTTP/404``.

Changing a method's behaviour
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the controller class::

    @wsgi.Controller.api_version("2.1", "2.3")
    def my_api_method(self, req, id):
        .... method_1 ...

    @wsgi.Controller.api_version("2.4") #noqa
    def my_api_method(self, req, id):
        .... method_2 ...

If a caller specified ``2.1``, ``2.2`` or ``2.3`` (or received the
default of ``2.1``) they would see the result from ``method_1``,
``2.4`` or later ``method_2``.

It is vital that the two methods have the same name, so the second of
them will need ``#noqa`` to avoid failing flake8's ``F811`` rule. The
two methods may be different in any kind of semantics (schema
validation, return values, response codes, etc)

A method with only small changes between versions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A method may have only small changes between microversions, in which
case you can decorate a private method::

    @api_version("2.1", "2.4")
    def _version_specific_func(self, req, arg1):
        pass

    @api_version(min_version="2.5") #noqa
    def _version_specific_func(self, req, arg1):
        pass

    def show(self, req, id):
        .... common stuff ....
        self._version_specific_func(req, "foo")
        .... common stuff ....

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


Other necessary changes
-----------------------

If you are adding a patch which adds a new microversion, it is
necessary to add changes to other places which describe your change:

* Update ``REST_API_VERSION_HISTORY`` in
  ``nova/api/openstack/api_version_request.py``

* Update ``_MAX_API_VERSION`` in
  ``nova/api/openstack/api_version_request.py``

* Add a verbose description to
  ``nova/api/openstack/rest_api_version_history.rst``.  There should
  be enough information that it could be used by the docs team for
  release notes.

Testing Microversioned API Methods
----------------------------------

Testing a microversioned API method is very similar to a normal controller
method test, you just need to add the ``X-OpenStack-Compute-API-Version``
header, for example::

    req = fakes.HTTPRequest.blank('/testable/url/endpoint')
    req.headers = {'X-OpenStack-Compute-API-Version': '2.2'}
    req.api_version_request = api_version.APIVersionRequest('2.6')

    controller = controller.TestableController()

    res = controller.index(req)
    ... assertions about the response ...

For many examples of testing, the canonical examples are in
``nova/tests/unit/api/openstack/compute/test_microversions.py``.
