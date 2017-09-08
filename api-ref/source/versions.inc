.. -*- rst -*-

==============
 API Versions
==============

In order to bring new features to users over time, the Nova API
supports versioning. There are two kinds of versions in Nova.

- ''major versions'', which have dedicated urls
- ''microversions'', which can be requested through the use of the
  ``X-OpenStack-Nova-API-Version`` header, or since microversion 2.27
  the ``OpenStack-API-Version`` header may also be used.

For more details about Microversions, please reference:
`Microversions
<https://developer.openstack.org/api-guide/compute/microversions.html>`_

.. note:: The maximum microversion supported by each release varies.
  Please reference:
  `API Microversion History
  <https://docs.openstack.org/nova/latest/reference/api-microversion-history.html>`__
  for API microversion history details.

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
  - links: links
  - min_version: version_min
  - status: version_status
  - updated: updated_version
  - version: version_max


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

This gets the details of a specific API at its root. Nearly all this
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
  - links: links
  - media-types: media_types
  - min_version: version_min
  - status: version_status
  - updated: updated_version
  - version: version_max


Response Example
----------------

This is an example of a ``GET /v2.1`` on a relatively current server.

.. literalinclude:: /../../doc/api_samples/versions/v21-version-get-resp.json
   :language: javascript
