.. -*- rst -*-

=========================================
 Host aggregates (os-aggregates, action)
=========================================

Creates and manages host aggregates. An aggregate assigns metadata to
groups of compute nodes. Aggregates are only visible to the cloud
provider.

Create Aggregate
================

.. rest_method:: POST /v2.1/{tenant_id}/os-aggregates

Creates an aggregate in an availability zone.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - name: aggregate_name
  - availability_zone: availability_zone

**Example Create Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-create-req.json
   :language: javascript

Response
--------

**Example Create Aggregate: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-create-resp.json
   :language: javascript

List Aggregates
===============

.. rest_method:: GET /v2.1/{tenant_id}/os-aggregates

Lists all aggregates. Includes the ID, name, and availability zone for each aggregate.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example List Aggregates: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-create-req.json
   :language: javascript

Response
--------

**Example List Aggregates: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-list-resp.json
   :language: javascript

Show Aggregate Details
======================

.. rest_method:: GET /v2.1/{tenant_id}/os-aggregates/{aggregate_id}

Shows details for an aggregate. Details include hosts and metadata.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

**Example Show Aggregate Details: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-create-req.json
   :language: javascript

Response
--------

**Example Show Aggregate Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-show-resp.json
   :language: javascript

Delete Aggregate
================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-aggregates/{aggregate_id}

Deletes an aggregate.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

Response
--------

Update Aggregate
================

.. rest_method:: PUT /v2.1/{tenant_id}/os-aggregates/{aggregate_id}

Updates either or both the name and availability zone for an aggregate.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

**Example Update Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-update-req.json
   :language: javascript

Response
--------

**Example Update Aggregate: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-update-resp.json
   :language: javascript

Add Host
========

.. rest_method:: POST /v2.1/{tenant_id}/os-aggregates/{aggregate_id}/action

Adds a host to an aggregate.

Specify the ``add_host`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

**Example Add Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-add-host-req.json
   :language: javascript

Response
--------

**Example Add Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-add-host-resp.json
   :language: javascript

Create Or Update Aggregate Metadata
===================================

.. rest_method:: POST /v2.1/{tenant_id}/os-aggregates/{aggregate_id}/action

Creates or replaces metadata for an aggregate.

Specify the ``set_metadata`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

**Example Create Or Update Aggregate Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-metadata-create-req.json
   :language: javascript

Response
--------

**Example Create Or Update Aggregate Metadata: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-metadata-create-resp.json
   :language: javascript

Remove Host
===========

.. rest_method:: POST /v2.1/{tenant_id}/os-aggregates/{aggregate_id}/action

Removes a host from an aggregate.

Specify the ``remove_host`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - aggregate_id: aggregate_id

**Example Remove Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-remove-host-req.json
   :language: javascript

Response
--------

**Example Remove Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-remove-host-resp.json
   :language: javascript

