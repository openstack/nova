.. -*- rst -*-

Show Console Output (Os-Getconsoleoutput Action)
================================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/action

Shows console output for a server instance.

Specify the ``os-getConsoleOutput`` action in the request body.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - os-getConsoleOutput: os-getConsoleOutput
  - length: length

**Example Get console output: JSON request**

.. literalinclude:: ../../doc/api_samples/servers-action/os-getConsoleOutput-create-req.json
   :language: javascript

Response
--------

**Example Get console output: JSON response**

.. literalinclude:: ../../doc/api_samples/servers-action/os-getConsoleOutput-create-resp.json
   :language: javascript

