.. -*- rst -*-

Add (Associate) Fixed Ip (Addfixedip Action)
============================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Adds a fixed IP address to a server instance, which associates that address with the server. The fixed IP address is retrieved from the network that you specify in the request.

Specify the ``addFixedIp`` action and the network ID in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202,,503,400,401,403,405,404,415,400,503,409

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - addFixedIp: addFixedIp

**Example Add (Associate) Fixed Ip (Addfixedip Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/multinic-add-fixed-ip-req.json
   :language: javascript

Response
^^^^^^^^

Remove (Disassociate) Fixed Ip (Removefixedip Action)
=====================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Removes, or disassociates, a fixed IP address from a server.

Specify the ``removeFixedIp`` action in the request body.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202,,503,400,401,403,405,404,415,400,503,409

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - removeFixedIp: removeFixedIp

**Example Remove (Disassociate) Fixed Ip (Removefixedip Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/multinic-remove-fixed-ip-req.json
   :language: javascript

Response
^^^^^^^^

