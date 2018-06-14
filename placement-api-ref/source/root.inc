============
API Versions
============

In order to bring new features to users over time, the Placement API
supports microversioning.  Microversions allow use of certain features on a
per-request basis via the ``OpenStack-API-Version`` header.  For example, to
request microversion 1.10, specify the header::

  OpenStack-API-Version: placement 1.10

For more details about Microversions, please reference:
`Microversions
<https://developer.openstack.org/api-guide/compute/microversions.html>`_

.. note:: The maximum microversion supported by each release varies.
  Please reference:
  `REST API Version History
  <https://docs.openstack.org/nova/latest/user/placement.html#rest-api-version-history>`__
  for API microversion history details.

List Versions
=============

.. rest_method:: GET /

Fetch information about all known major versions of the placement API,
including information about the minimum and maximum microversions.

.. note:: At this time there is only one major version of the placement API:
          version 1.0.

Normal Response Codes: 200

Response
--------

.. rest_parameters:: parameters.yaml

  - versions: versions
  - id: version_id
  - min_version: version_min
  - max_version: version_max
  - status: version_status
  - links: version_links

Response Example
----------------

.. literalinclude:: ./samples/root/get-root.json
   :language: javascript
