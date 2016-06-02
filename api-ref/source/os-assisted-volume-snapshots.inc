.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==========================================================
 Assisted volume snapshots (os-assisted-volume-snapshots)
==========================================================

Creates and deletes snapshots through an emulator/hypervisor. The qcow2
file format is supported.

An internal snapshot that lacks storage such as NFS or GlusterFS can use
an emulator/hypervisor to add the snapshot feature.

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
  - snapshot_id: snapshot_id
  - type: type
  - new_file: new_file

**Example Create Assisted Volume Snapshots: JSON request**

.. literalinclude:: ../../doc/api_samples/os-assisted-volume-snapshots/snapshot-create-assisted-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - id: id
  - volume_id: volume_id

**Example Create Assisted Volume Snapshots: JSON response**

.. literalinclude:: ../../doc/api_samples/os-assisted-volume-snapshots/snapshot-create-assisted-resp.json
   :language: javascript

Delete Assisted Volume Snapshot
===============================

.. rest_method:: DELETE /os-assisted-volume-snapshots/{snapshot_id}

Deletes an assisted volume snapshot.

To make this request, add the ``delete_info`` query parameter to the URI, as follows:

DELETE /os-assisted-volume-snapshots?delete_info='{"volume_id": "521752a6-acf6-4b2d-bc7a-119f9148cd8c"}'

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - snapshot_id: snapshot_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - delete_info: delete_info

Response
--------

