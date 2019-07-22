.. -*- rst -*-

=========================================================
 Volume extension (os-volumes, os-snapshots) (DEPRECATED)
=========================================================

.. warning::

   These APIs are proxy calls to the Volume service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Volume APIs
   <https://docs.openstack.org/api-ref/block-storage/v3/index.html>`__.

Manages volumes and snapshots for use with the Compute API.
Lists, shows details, creates, and deletes volumes and snapshots.

List Volumes
============

.. rest_method:: GET /os-volumes

Lists the volumes associated with the account.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - volumes: volumes
  - attachments: volumeAttachments
  - attachments.device: attachment_device_resp
  - attachments.id: attachment_id_resp
  - attachments.serverId: attachment_server_id_resp
  - attachments.volumeId: attachment_volumeId_resp
  - availabilityZone: OS-EXT-AZ:availability_zone
  - createdAt: created
  - displayDescription: display_description
  - displayName: display_name
  - id: volume_id_resp
  - metadata: metadata_object 
  - size: size
  - snapshotId: snapshot_id
  - status: volume_status
  - volumeType: volume_type

|

**Example List Volumes**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-index-resp.json
   :language: javascript

Create Volume
=============

.. rest_method:: POST /os-volumes

Creates a new volume.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - volume: volume
  - size: size
  - availability_zone: OS-EXT-AZ:availability_zone_optional
  - display_name: display_name_optional
  - display_description: display_description_optional
  - metadata: metadata
  - volume_type: volume_type_optional
  - snapshot_id: snapshot_id_optional

**Example Create Volume**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - volume: volume
  - attachments: volumeAttachments
  - attachments.device: attachment_device_resp
  - attachments.id: attachment_id_resp
  - attachments.serverId: attachment_server_id_resp
  - attachments.volumeId: attachment_volumeId_resp
  - availabilityZone: OS-EXT-AZ:availability_zone
  - createdAt: created
  - displayName: display_name
  - displayDescription: display_description
  - id: volume_id_resp
  - metadata: metadata_object 
  - size: size
  - snapshotId: snapshot_id
  - status: volume_status
  - volumeType: volume_type

|

**Example Create Volume**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-post-resp.json
   :language: javascript

List Volumes With Details
=========================

.. rest_method:: GET /os-volumes/detail

Lists all volumes with details.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - volumes: volumes
  - attachments: volumeAttachments
  - attachments.device: attachment_device_resp
  - attachments.id: attachment_id_resp
  - attachments.serverId: attachment_server_id_resp
  - attachments.volumeId: attachment_volumeId_resp
  - availabilityZone: OS-EXT-AZ:availability_zone
  - createdAt: created
  - displayName: display_name
  - displayDescription: display_description
  - id: volume_id_resp
  - metadata: metadata_object 
  - size: size
  - snapshotId: snapshot_id
  - status: volume_status
  - volumeType: volume_type

|

**Example List Volumes With Details**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-detail-resp.json
   :language: javascript

Show Volume Details
===================

.. rest_method:: GET /os-volumes/{volume_id}

Shows details for a given volume.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - volume_id: volume_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - volume: volume
  - attachments: volumeAttachments
  - attachment.device: attachment_device_resp
  - attachments.id: attachment_id_resp
  - attachments.serverId: attachment_server_id_resp
  - attachments.volumeId: attachment_volumeId_resp
  - availabilityZone: OS-EXT-AZ:availability_zone
  - createdAt: created
  - displayName: display_name
  - displayDescription: display_description
  - id: volume_id_resp
  - metadata: metadata_object 
  - size: size
  - snapshotId: snapshot_id
  - status: volume_status
  - volumeType: volume_type

|

**Example Show Volume Details**

.. literalinclude:: ../../doc/api_samples/os-volumes/os-volumes-get-resp.json
   :language: javascript

Delete Volume
=============

.. rest_method:: DELETE /os-volumes/{volume_id}

Deletes a volume.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - volume_id: volume_id_path

Response
--------

There is no body content for the response of a successful DELETE query


List Snapshots
==============

.. rest_method:: GET /os-snapshots

Lists snapshots.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - snapshots: snapshots
  - id: snapshot_id
  - createdAt: created
  - displayName: snapshot_name
  - displayDescription: snapshot_description
  - size: size
  - status: snapshot_status
  - volumeId: volume_id

|

**Example List Snapshots**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-list-resp.json
   :language: javascript

Create Snapshot
===============

.. rest_method:: POST /os-snapshots

Creates a new snapshot.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - snapshot: snapshot
  - volume_id: volume_id
  - display_description: snapshot_description_optional
  - display_name: snapshot_name_optional
  - force: force_snapshot

**Example Create Snapshot**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshot-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - snapshot: snapshot
  - id: snapshot_id
  - createdAt: created
  - displayName: snapshot_name
  - displayDescription: snapshot_description
  - volumeId: volume_id
  - size: size
  - status: snapshot_status

**Example Create Snapshot**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshot-create-resp.json
   :language: javascript

List Snapshots With Details
===========================

.. rest_method:: GET /os-snapshots/detail

Lists all snapshots with details.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - snapshots: snapshots
  - id: snapshot_id
  - createdAt: created
  - displayName: snapshot_name
  - displayDescription: snapshot_description
  - volumeId: volume_id
  - size: size
  - status: snapshot_status

|

**Example List Snapshots With Details**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-detail-resp.json
   :language: javascript

Show Snapshot Details
=====================

.. rest_method:: GET /os-snapshots/{snapshot_id}

Shows details for a given snapshot.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - snapshot_id: snapshot_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - snapshot: snapshot
  - id: snapshot_id
  - createdAt: created
  - displayName: snapshot_name
  - displayDescription: snapshot_description
  - volumeId: volume_id
  - size: size
  - status: snapshot_status

|

**Example Show Snapshot Details**

.. literalinclude:: ../../doc/api_samples/os-volumes/snapshots-show-resp.json
   :language: javascript

Delete Snapshot
===============

.. rest_method:: DELETE /os-snapshots/{snapshot_id}

Deletes a snapshot from the account.

This operation is asynchronous. You must list snapshots repeatedly to determine whether the snapshot was deleted.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - snapshot_id: snapshot_id_path


Response
--------

There is no body content for the response of a successful DELETE query
