.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

================================
 Host aggregates (os-aggregates)
================================

Creates and manages host aggregates. An aggregate assigns metadata to
groups of compute nodes. Aggregates are only visible to the cloud
provider.

List Aggregates
===============

.. rest_method:: GET /os-aggregates

Lists all aggregates. Includes the ID, name, and availability zone for each aggregate.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

**Example List Aggregates: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-list-get-resp.json
   :language: javascript

Create Aggregate
================

.. rest_method:: POST /os-aggregates

Creates an aggregate in an availability zone.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - name: aggregate_name
  - availability_zone: availability_zone

**Example Create Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-post-req.json
   :language: javascript

Response
--------

**Example Create Aggregate: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-post-resp.json
   :language: javascript

Show Aggregate Details
======================

.. rest_method:: GET /os-aggregates/{aggregate_id}

Shows details for an aggregate. Details include hosts and metadata.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

Response
--------

**Example Show Aggregate Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-get-resp.json
   :language: javascript

Update Aggregate
================

.. rest_method:: PUT /os-aggregates/{aggregate_id}

Updates either or both the name and availability zone for an aggregate.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

**Example Update Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-update-post-req.json
   :language: javascript

Response
--------

**Example Update Aggregate: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-update-post-resp.json
   :language: javascript

Delete Aggregate
================

.. rest_method:: DELETE /os-aggregates/{aggregate_id}

Deletes an aggregate.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

Response
--------

Add Host
========

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Adds a host to an aggregate.

Specify the ``add_host`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

**Example Add Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-add-host-post-req.json
   :language: javascript

Response
--------

**Example Add Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-add-host-post-resp.json
   :language: javascript

Remove Host
===========

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Removes a host from an aggregate.

Specify the ``remove_host`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

**Example Remove Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-remove-host-post-req.json
   :language: javascript

Response
--------

**Example Remove Host: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-remove-host-post-resp.json
   :language: javascript

Create Or Update Aggregate Metadata
===================================

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Creates or replaces metadata for an aggregate.

Specify the ``set_metadata`` action in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id

**Example Create Or Update Aggregate Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-metadata-post-req.json
   :language: javascript

Response
--------

**Example Create Or Update Aggregate Metadata: JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregates-metadata-post-resp.json
   :language: javascript
