.. -*- rst -*-

==========================================================
 Assisted volume snapshots (os-assisted-volume-snapshots)
==========================================================

Creates and deletes snapshots through an emulator/hypervisor. Only qcow2
file format is supported.

This API is only implemented by the libvirt compute driver.

An internal snapshot that lacks storage such as NFS can use
an emulator/hypervisor to add the snapshot feature.
This is used to enable snapshot of volumes on backends such as NFS
by storing data as qcow2 files on these volumes.

This API is only ever called by Cinder, where it is used to create a snapshot
for drivers that extend the remotefs Cinder driver.

Create Assisted Volume Snapshots
================================

.. rest_method:: POST /os-assisted-volume-snapshots

Creates an assisted volume snapshot.

Normal response codes: 200

Error response codes: badRequest(400),unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml


  - snapshot: snapshot
  - volume_id: volume_id
  - create_info: create_info
  - create_info.snapshot_id: snapshot_id
  - create_info.type: type-os-assisted-volume-snapshot
  - create_info.new_file: new_file
  - create_info.id: create_info_id

**Example Create Assisted Volume Snapshots: JSON request**

.. literalinclude:: ../../doc/api_samples/os-assisted-volume-snapshots/snapshot-create-assisted-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - snapshot: snapshot
  - id: create_info_id_resp
  - volumeId: volume_id

**Example Create Assisted Volume Snapshots: JSON response**

.. literalinclude:: ../../doc/api_samples/os-assisted-volume-snapshots/snapshot-create-assisted-resp.json
   :language: javascript

Delete Assisted Volume Snapshot
===============================

.. rest_method:: DELETE /os-assisted-volume-snapshots/{snapshot_id}

Deletes an assisted volume snapshot.

To make this request, add the ``delete_info`` query parameter to the URI, as follows:

DELETE /os-assisted-volume-snapshots/421752a6-acf6-4b2d-bc7a-119f9148cd8c?delete_info='{"volume_id": "521752a6-acf6-4b2d-bc7a-119f9148cd8c"}'

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - snapshot_id: snapshot_id_path
  - delete_info: delete_info

Response
--------

There is no body content for the response of a successful DELETE query
