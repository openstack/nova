.. -*- rst -*-

============================================
 Flavors with extended attributes (flavors)
============================================

Shows information about flavors.

List Flavors
============

.. rest_method:: GET /v2.1/{tenant_id}/flavors

Lists flavors.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - minDisk: minDisk
  - minRam: minRam
  - sort_key: sort_key
  - sort_dir: sort_dir
  - limit: limit
  - marker: marker

Response
--------

**Example List Flavors: JSON response**

.. literalinclude:: ../../doc/api_samples/flavors/flavors-list-resp.json
   :language: javascript

Create Flavor
=============

.. rest_method:: POST /v2.1/{tenant_id}/flavors

Creates a flavor.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example Create Flavor: JSON request**

.. literalinclude:: ../../doc/api_samples/flavor-manage/flavor-create-post-req.json
   :language: javascript

Response
--------

**Example Create Flavor: JSON response**

.. literalinclude:: ../../doc/api_samples/flavor-manage/flavor-create-post-resp.json
   :language: javascript

Show Flavor Details
===================

.. rest_method:: GET /v2.1/{tenant_id}/flavors/{flavor_id}

Shows details for a flavor.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

Response
--------

**Example Show Flavor Details: JSON response**

.. literalinclude:: ../../doc/api_samples/flavors/flavor-get-resp.json
   :language: javascript

Delete Flavor
=============

.. rest_method:: DELETE /v2.1/{tenant_id}/flavors/{flavor_id}

Deletes a flavor.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - flavor_id: flavor_id

Response
--------

List Flavors With Details
=========================

.. rest_method:: GET /v2.1/{tenant_id}/flavors/detail

Lists flavors with details.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - minDisk: minDisk
  - minRam: minRam
  - sort_key: sort_key
  - sort_dir: sort_dir
  - limit: limit
  - marker: marker

Response
--------

**Example List Flavors With Details: JSON response**

.. literalinclude:: ../../doc/api_samples/flavors/flavors-detail-resp.json
   :language: javascript

