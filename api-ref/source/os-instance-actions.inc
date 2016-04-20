.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=======================================================
 Servers - list actions (servers, os-instance-actions)
=======================================================

All users can list available actions for a server.

All users can show details for a server action; however, only
administrators can view server events in server action details.

List Actions For Server
=======================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-instance-actions

Lists actions for a server.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
--------

**Example List Actions For Server: JSON response**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/instance-actions-list-resp.json
   :language: javascript

Show Server Action Details
==========================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-instance-actions/{request_id}

Shows details for a server action.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - request_id: request_id

Response
--------

**Example Show Server Action Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-instance-actions/instance-action-get-resp.json
   :language: javascript

