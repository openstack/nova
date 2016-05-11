.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

===================================================================
 Servers with volume attachments (servers, os-volume\_attachments)
===================================================================

Attaches volumes that are created through the volume API to server
instances. Also, lists volume attachments for a server instance, shows
details for a volume attachment, and detaches a volume.

List volume attachments for an instance
=======================================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-volume_attachments

List volume attachments for an instance.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

Response
--------

Attach a volume to an instance
==============================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/os-volume_attachments

Attach a volume to an instance.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

Response
--------

Show a detail of a volume attachment
====================================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-volume_attachments/{attachment_id}

Show a detail of a volume attachment.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

Response
--------

Update a volume attachment
==========================

.. rest_method:: PUT /v2.1/{tenant_id}/servers/{server_id}/os-volume_attachments/{attachment_id}

Update a volume attachment.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

Response
--------

Detach a volume from an instance
================================

.. rest_method:: DELETE /v2.1/{tenant_id}/servers/{server_id}/os-volume_attachments/{attachment_id}

Detach a volume from an instance.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

Response
--------
