.. -*- rst -*-

================================================
 Servers password (servers, os-server-password)
================================================

Shows the encrypted administrative password. Also, clears the encrypted
administrative password for a server, which removes it from the metadata
server.

Show Server Password
====================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-server-password

Shows the administrative password for a server.

This operation calls the metadata service to query metadata information and does not read password information from the server itself.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

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

**Example Show Server Password: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-password/get-password-resp.json
   :language: javascript

Clear Admin Password
====================

.. rest_method:: DELETE /v2.1/{tenant_id}/servers/{server_id}/os-server-password

Clears the encrypted administrative password for a server, which removes it from the metadata server.

This action does not actually change the instance server password.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 204

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
--------

