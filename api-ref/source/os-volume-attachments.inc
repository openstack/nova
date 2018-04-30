.. -*- rst -*-

===================================================================
 Servers with volume attachments (servers, os-volume\_attachments)
===================================================================

Attaches volumes that are created through the volume API to server
instances. Also, lists volume attachments for a server, shows
details for a volume attachment, and detaches a volume.

List volume attachments for an instance
=======================================

.. rest_method:: GET /servers/{server_id}/os-volume_attachments

List volume attachments for an instance.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - volumeAttachments: volumeAttachments
  - device: device_resp
  - id: attachment_id_required
  - serverId: server_id
  - volumeId: volumeId_resp

**Example List volume attachments for an instance: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/list-volume-attachments-resp.json
   :language: javascript

Attach a volume to an instance
==============================

.. rest_method:: POST /servers/{server_id}/os-volume_attachments

Attach a volume to an instance.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

.. note:: From v2.20 attach a volume to an instance in SHELVED or SHELVED_OFFLOADED
          state is allowed.

.. note:: From v2.60, attaching a multiattach volume to multiple instances is
          supported for instances that are not SHELVED_OFFLOADED. The ability
          to actually support a multiattach volume depends on the volume type
          and compute hosting the instance.

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - volumeAttachment: volumeAttachment_post
  - volumeId: volumeId
  - device: device
  - tag: device_tag_bdm_attachment

**Example Attach a volume to an instance: JSON request**

.. literalinclude:: ../../doc/api_samples/os-volumes/attach-volume-to-server-req.json
   :language: javascript

**Example Attach a volume to an instance and tag it (v2.49): JSON request**

.. literalinclude:: ../../doc/api_samples/os-volumes/v2.49/attach-volume-to-server-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - volumeAttachment: volumeAttachment
  - device: device_resp
  - id: attachment_id_required
  - serverId: server_id
  - volumeId: volumeId_resp

**Example Attach a volume to an instance: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/attach-volume-to-server-resp.json
   :language: javascript

Show a detail of a volume attachment
====================================

.. rest_method:: GET /servers/{server_id}/os-volume_attachments/{volume_id}

Show a detail of a volume attachment.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - volume_id: volume_id_attached_path

Response
--------

.. rest_parameters:: parameters.yaml

  - volumeAttachment: volumeAttachment
  - device: device_resp
  - id: attachment_id_required
  - serverId: server_id
  - volumeId: volumeId_resp

**Example Show a detail of a volume attachment: JSON response**

.. literalinclude:: ../../doc/api_samples/os-volumes/volume-attachment-detail-resp.json
   :language: javascript

Update a volume attachment
==========================

.. rest_method:: PUT /servers/{server_id}/os-volume_attachments/{volume_id}

Update a volume attachment.

.. note:: This action only valid when the server is in ACTIVE, PAUSED and RESIZED state,
          or a conflict(409) error will be returned.

Policy defaults enable only users with the administrative role or
the owner of the server to perform this operation. Cloud providers
can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - volume_id: volume_id_swap_src
  - volumeAttachment: volumeAttachment_put
  - volumeId: volumeId_swap

**Example Update a volume attachment: JSON request**

.. literalinclude:: ../../doc/api_samples/os-volumes/update-volume-req.json
   :language: javascript

Response
--------

No body is returned on successful request.

Detach a volume from an instance
================================

.. rest_method:: DELETE /servers/{server_id}/os-volume_attachments/{volume_id}

Detach a volume from an instance.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

.. note:: From v2.20 detach a volume from an instance in SHELVED or SHELVED_OFFLOADED
          state is allowed.

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - volume_id: volume_id_to_detach_path

Response
--------

No body is returned on successful request.
