.. -*- rst -*-

Evacuate Server (Evacuate Action)
=================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Evacuates a server from a failed host to a new one.

Specify the ``evacuate`` action in the request body.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - evacuate: evacuate
  - host: host
  - adminPass: adminPass_evacuate_rebuild

**Example Evacuate Server (Evacuate Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/evacuate-req.json
   :language: javascript

Response
--------

**Example Evacuate Server (Evacuate Action): JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/evacuate-resp.json
   :language: javascript

