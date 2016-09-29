.. -*- rst -*-

=====================================
 Extensions (extensions) (DEPRECATED)
=====================================

Lists available extensions and shows information for an extension, by
alias.

Nova originally supported the concept of API extensions, that allowed
implementations of Nova to change the API (add new resources, or
attributes to existing resource objects) via extensions. In an attempt
to expose to the user what was supported in a particular site, the
extensions resource provided a list of extensions and detailed
information on each. The net result was gratuitous differentiation in
the API that required all users of OpenStack clouds to write specific
code to interact with every cloud.

As such, the entire extensions concept is deprecated, and will be
removed in the near future.

For information about extensions, see `Extensions
<http://developer.openstack.org/api-guide/compute/extensions.html>`__.

List Extensions
===============

.. rest_method:: GET /extensions

Lists all extensions to the API.

Normal response codes: 200

Error response codes: unauthorized(401)


Response
--------

.. rest_parameters:: parameters.yaml

  - extensions: extensions
  - name: extension_name
  - alias: alias
  - links: extension_links
  - namespace: namespace
  - description: extension_description
  - updated: updated

**Example List Extensions**

Lists all extensions to the API.

.. literalinclude:: ../../doc/api_samples/extension-info/extensions-list-resp.json
   :language: javascript


Show Extension Details
======================

.. rest_method:: GET /extensions/{alias}

Shows details for an extension, by alias.

Normal response codes: 200

Error response codes: unauthorized(401), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - alias: alias

Response
--------

.. rest_parameters:: parameters.yaml

  - extension: extension
  - name: extension_name
  - alias: alias
  - links: extension_links
  - namespace: namespace
  - description: extension_description
  - updated: updated

**Example Show Extension Details**

Shows details about the ``os-agents`` extension.

.. literalinclude:: ../../doc/api_samples/extension-info/extensions-get-resp.json
   :language: javascript
