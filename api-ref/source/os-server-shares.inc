.. -*- rst -*-

===================================================================
 Servers with shares attachments (servers, shares)
===================================================================

Attaches shares that are created through the Manila share API to server
instances. Also, lists share attachments for a server, shows
details for a share attachment, and detaches a share (New in version 2.97).

List share attachments for an instance
=======================================

.. rest_method:: GET /servers/{server_id}/shares

List share attachments for an instance.

Normal response codes: 200

Error response codes: badrequest(400), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - shares: shares_body
  - share_id: share_id_body
  - status: share_status_body
  - tag: share_tag_body


**Example List share attachments for an instance: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-shares/v2.97/server-shares-list-resp.json
   :language: javascript


Attach a share to an instance
==============================

.. rest_method:: POST /servers/{server_id}/shares

Attach a share to an instance.

Normal response codes: 201

Error response codes: badRequest(400), forbidden(403), itemNotFound(404), conflict(409)

.. note:: This action is only valid when the server is in ``STOPPED`` state.

.. note:: This action also needs specific configurations, check the documentation requirements to configure
          your environment and support this feature.

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - share_id: share_id_body
  - tag: share_tag_body

**Example Attach a share to an instance: JSON request**

.. literalinclude:: ../../doc/api_samples/os-server-shares/v2.97/server-shares-create-req.json
   :language: javascript


Response
--------

.. rest_parameters:: parameters.yaml

  - shares: shares_body
  - share_id: share_id_body
  - status: share_status_body
  - tag: share_tag_body

**Example Attach a share to an instance: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-shares/v2.97/server-shares-create-resp.json
   :language: javascript


Show a detail of a share attachment
====================================

.. rest_method:: GET /servers/{server_id}/shares/{share_id}

Show a detail of a share attachment.

Normal response codes: 200

Error response codes: badRequest(400), forbidden(403), itemNotFound(404)


Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - share_id: share_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - share: share_body
  - uuid: share_uuid_body
  - share_id: share_id_body
  - status: share_status_body
  - tag: share_tag_body
  - export_location: share_export_location_body

.. note:: Optional fields can only be seen by admins.

**Example Show a detail of a share attachment: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-shares/v2.97/server-shares-show-resp.json
   :language: javascript

**Example Show a detail of a share attachment with admin rights: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-shares/v2.97/server-shares-admin-show-resp.json
   :language: javascript


Detach a share from an instance
================================

.. rest_method:: DELETE /servers/{server_id}/shares/{share_id}

Detach a share from an instance.

Normal response codes: 200

Error response codes: badRequest(400), forbidden(403), itemNotFound(404), conflict(409)

.. note:: This action is only valid when the server is in ``STOPPED`` or ``ERROR`` state.


Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - share_id: share_id_path

Response
--------

No body is returned on successful request.
