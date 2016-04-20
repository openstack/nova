.. -*- rst -*-

=============================================
 Volume extension (os-volumes, os-snapshots)
=============================================

Manages volumes and snapshots for use with the Compute API.

List Volumes
============

.. rest_method:: GET /v2.1/{tenant_id}/os-volumes

Lists the volumes associated with the account.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Volumes: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-index-resp.json
   :language: javascript

Create Volume
=============

.. rest_method:: POST /v2.1/{tenant_id}/os-volumes

Creates a volume.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - volume: volume
  - display_name: display_name
  - display_description: display_description
  - size: size
  - volume_type: volume_type
  - metadata: metadata
  - availability_zone: availability_zone
  - snapshot_id: snapshot_id

**Example Create Volume: JSON request**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-post-req.json
   :language: javascript

Response
--------

**Example Create Volume: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-post-resp.json
   :language: javascript

List Volumes With Details
=========================

.. rest_method:: GET /v2.1/{tenant_id}/os-volumes/detail

Lists all volumes with details.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Volumes With Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-detail-resp.json
   :language: javascript

Show Volume Details
===================

.. rest_method:: GET /v2.1/{tenant_id}/os-volumes/{volume_id}

Shows details for a volume.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - volume_id: volume_id

Response
--------

**Example Show Volume Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-get-resp.json
   :language: javascript

Delete Volume
=============

.. rest_method:: DELETE /v2.1/{tenant_id}/os-volumes/{volume_id}

Deletes a volume.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - volume_id: volume_id

Response
--------

Create Snapshot
===============

.. rest_method:: POST /v2.1/{tenant_id}/os-snapshots

Creates a snapshot.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - snapshot: snapshot

**Example Create Snapshot: JSON request**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshot-create-req.json
   :language: javascript

Response
--------

**Example Create Snapshot: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshot-create-resp.json
   :language: javascript

List Snapshots
==============

.. rest_method:: GET /v2.1/{tenant_id}/os-snapshots

Lists snapshots.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Snapshots: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-list-resp.json
   :language: javascript

List Snapshots With Details
===========================

.. rest_method:: GET /v2.1/{tenant_id}/os-snapshots/detail

Lists all snapshots with details.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Snapshots With Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-detail-resp.json
   :language: javascript

Show Snapshot Details
=====================

.. rest_method:: GET /v2.1/{tenant_id}/os-snapshots/{snapshot_id}

Shows details for a snapshot.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - snapshot_id: snapshot_id

Response
--------

**Example Show Snapshot Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-show-resp.json
   :language: javascript

Delete Snapshot
===============

.. rest_method:: DELETE /v2.1/{tenant_id}/os-snapshots/{snapshot_id}

Deletes a snapshot from the account.

This operation is asynchronous. You must list snapshots repeatedly to determine whether the snapshot was deleted.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - snapshot_id: snapshot_id

Response
--------
