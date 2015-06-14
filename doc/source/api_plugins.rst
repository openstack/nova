API Plugins
===========

Background
----------

Nova has two API plugin frameworks, one for the original V2 API and
one for what we call V2.1 which also supports V2.1 microversions. The
V2.1 API acts from a REST API user point of view in an identical way
to the original V2 API. V2.1 is implemented in the same framework as
microversions, with the version requested being 2.1.

The V2 API is now frozen and with the exception of significant bugs no
change should be made to the V2 API code. API changes should only be
made through V2.1 microversions.

This document covers how to write plugins for the v2.1 framework. A
`microversions specific document
<http://docs.openstack.org/developer/nova/devref/api_microversions.html>`_
covers the details around what is required for the microversions
part. It does not cover V2 plugins which should no longer be developed.

There may still be references to a v3 API both in comments and in the
directory path of relevant files. This is because v2.1 first started
out being called v3 rather than v2.1. Where you see references to v3
you can treat it as a reference to v2.1 with or without microversions
support.

The original V2 API plugins live in ``nova/api/openstack/compute/contrib``
and the V2.1 plugins live in ``nova/api/openstack/compute/plugins/v3``.

Note that any change to the Nova API to be merged will first require a
spec be approved first. See `here <https://github.com/openstack/nova-specs>`_
for the appropriate repository. For guidance on the design of the API
please refer to the `Openstack API WG
<https://wiki.openstack.org/wiki/API_Working_Group>`_


Basic plugin structure
----------------------

A very basic skeleton of a v2.1 plugin can be seen `here in the unittests <http://git.openstack.org/cgit/openstack/nova/tree/nova/tests/unit/api/openstack/compute/test_plugins/basic.py>`_. An annotated version below::

    """Basic Test Extension"""

    from nova.api.openstack import extensions
    from nova.api.openstack import wsgi


    ALIAS = 'test-basic'
    # ALIAS needs to be unique and should be of the format
    # ^[a-z]+[a-z\-]*[a-z]$

    class BasicController(wsgi.Controller):

        # Define support for GET on a collection
        def index(self, req):
            data = {'param': 'val'}
            return data

        # Defining a method implements the following API responses:
        #   delete -> DELETE
        #   update -> PUT
        #   create -> POST
        #   show -> GET
        # If a method is not definied a request to it will be a 404 response

        # It is also possible to define support for further responses
        # See `servers.py <http://git.openstack.org/cgit/openstack/nova/tree/nova/nova/api/openstack/compute/plugins/v3/servers.py>`_.


    class Basic(extensions.V3APIExtensionBase):
        """Basic Test Extension."""

        name = "BasicTest"
        alias = ALIAS
        version = 1

        # Both get_resources and get_controller_extensions must always
        # be definied by can return an empty array
        def get_resources(self):
            resource = extensions.ResourceExtension('test', BasicController())
            return [resource]

        def get_controller_extensions(self):
            return []

All of these plugin files should live in the ``nova/api/openstack/compute/plugins/v3`` directory.


Policy
~~~~~~

Policy (permission) is defined ``etc/nova/policy.json``. Implementation of policy
is changing a bit at the moment. Will add more to this document or reference
another one in the future. Note that a 'discoverable' policy needs to be added
for each plugin that you wish to appear in the ``/extension`` output. Also
look at the authorize call in plugins currently merged.


Support files
-------------

At least one entry needs to made in ``setup.cfg`` for each plugin.
An entry point for the plugin must be added to nova.api.v3.extensions
even if no resource or controller is added. Other entry points available
are

* Modify create behaviour (nova.api.v3.extensions.server.create)
* Modify rebuild behaviour (nova.api.v3.extensions.server.rebuild)
* Modify update behaviour (nova.api.v3.extensions.server.update)
* Modify resize behaviour (nova.api.v3.extensions.server.resize)

These are essentially hooks into the servers plugin which allow other
plugins to modify behaviour without having to modify servers.py. In
the past not having this capability led to very large chunks of
unrelated code being added to servers.py which was difficult to
maintain.


Unit Tests
----------

Should write something more here. But you need to have
both unit and functional tests.


Functional tests and API Samples
--------------------------------

Should write something here

Commit message tags
-------------------

Please ensure you add the ``DocImpact`` tag along with a short
description for any API change.
