.. -*- rst -*-

==============
 API Versions
==============

In order to bring new features to users over time, the Nova API
supports versioning. There are two kinds of versions in Nova.

- ''major versions'', which have dedicated urls
- ''microversions'', which can be requested through the use of the
  ``X-OpenStack-Nova-API-Version`` header or since microversion 2.27
  the ``OpenStack-API-Version`` header may also be used.

For more detail about Microversion, please reference:
`Microversions
<http://developer.openstack.org/api-guide/compute/microversions.html>`_

The Version APIs work differently from other APIs as they *do not*
require authentication.

List All Major Versions
=======================

.. rest_method:: GET /

This fetches all the information about all known major API versions in
the deployment. Links to more specific information will be provided
for each API version, as well as information about supported min and
max microversions.

Normal Response Codes: 200

Response
--------

.. rest_parameters:: parameters.yaml

  - versions: versions
  - id: version_id
  - status: version_status
  - links: links
  - version: version_max
  - min_version: version_min

.. note::

   The ``updated`` parameter in the response is vestigial and provides
   no useful information.

Response Example
----------------

This demonstrates the expected response from a bleeding edge server
that supports up to the current microversion. When querying OpenStack
environments you will typically find the current microversion on the
v2.1 API is lower than listed below.

.. literalinclude:: /../../doc/api_samples/versions/versions-get-resp.json
   :language: javascript


Show Details of Specific API Version
====================================

.. rest_method:: GET /{api_version}

This gets the details of a specific API at it's root. Nearly all this
information exists at the API root, so this is mostly a redundant
operation.

.. TODO(sdague) we should probably deprecate this call as everything
   that's needed is really in the root now

Normal Response Codes: 200

Request
-------

.. rest_parameters:: parameters.yaml

   - api_version: api_version

Response
--------

.. rest_parameters:: parameters.yaml

  - version: version
  - id: version_id
  - status: version_status
  - links: links
  - version: version_max
  - min_version: version_min

.. note::

   The ``updated`` and ``media-types`` parameters in the response are
   vestigial and provide no useful information. They will probably be
   deprecated and removed in the future.


Response Example
----------------

This is an example of a ``GET /v2.1`` on a relatively current server.

.. literalinclude:: /../../doc/api_samples/versions/v21-version-get-resp.json
   :language: javascript
