.. -*- rst -*-

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

.. rest_parameters:: parameters.yaml

  - aggregates: aggregates
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: aggregate_host_list
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example List Aggregates (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregates-list-get-resp.json
   :language: javascript

Create Aggregate
================

.. rest_method:: POST /os-aggregates

Creates an aggregate. If specifying an option availability_zone, the aggregate is
created as an availability zone and the availability zone is visible to normal users.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - name: aggregate_name
  - availability_zone: aggregate_az_optional

**Example Create Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - id: aggregate_id_body
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Create Aggregate (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregate-post-resp.json
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

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: hosts
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Show Aggregate Details (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregates-get-resp.json
   :language: javascript

Update Aggregate
================

.. rest_method:: PUT /os-aggregates/{aggregate_id}

Updates either or both the name and availability zone for an aggregate.
If the aggregate to be updated has host that already in the given
availability zone, the request will fail with 400 error.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id
  - aggregate: aggregate
  - name: aggregate_name_optional
  - availability_zone: aggregate_az_optional

**Example Update Aggregate: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-update-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: hosts
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Update Aggregate (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregate-update-post-resp.json
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

There is no body content for the response of a successful DELETE action.

Add Host
========

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Adds a host to an aggregate.

Specify the ``add_host`` action and host name in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id
  - add_host: aggregate_add_host
  - host: host_name_body

**Example Add Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-add-host-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: hosts
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Add Host (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregates-add-host-post-resp.json
   :language: javascript

Remove Host
===========

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Removes a host from an aggregate.

Specify the ``remove_host`` action and host name in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id
  - remove_host: aggregate_remove_host
  - host: host_name_body

**Example Remove Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-remove-host-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: hosts
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Remove Host (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregates-remove-host-post-resp.json
   :language: javascript

Create Or Update Aggregate Metadata
===================================

.. rest_method:: POST /os-aggregates/{aggregate_id}/action

Creates or replaces metadata for an aggregate.

Specify the ``set_metadata`` action and metadata info in the request body.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - aggregate_id: aggregate_id
  - set_metadata: set_metadata
  - metadata: metadata_object 

**Example Create Or Update Aggregate Metadata: JSON request**

.. literalinclude:: ../../doc/api_samples/os-aggregates/aggregate-metadata-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - aggregate: aggregate
  - availability_zone: aggregate_az
  - created_at: created
  - deleted_at: deleted_at
  - deleted: deleted
  - hosts: hosts
  - id: aggregate_id_body
  - metadata: aggregate_metadata
  - name: aggregate_name
  - updated_at: updated_consider_null
  - uuid: aggregate_uuid

**Example Create Or Update Aggregate Metadata (v2.41): JSON response**

.. literalinclude:: ../../doc/api_samples/os-aggregates/v2.41/aggregates-metadata-post-resp.json
   :language: javascript
