.. -*- rst -*-

Evacuate Server (evacuate Action)
=================================

.. rest_method:: POST /servers/{server_id}/action

Evacuates a server from a failed host to a new host.

- Specify the ``evacuate`` action in the request body.
- In the request body, if ``onSharedStorage`` is set, then do not set ``adminPass``.
- The target host should not be the same as the instance host.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - evacuate: evacuate
  - host: host
  - adminPass: adminPass_evacuate_request
  - onSharedStorage: on_shared_storage
  - force: force_evacuate

|

**Example Evacuate Server (evacuate Action)**

.. literalinclude:: ../../doc/api_samples/os-evacuate/server-evacuate-req.json
   :language: javascript


Response
--------

.. rest_parameters:: parameters.yaml

  - adminPass: adminPass_evacuate

.. note:: API does not return any Response for Microversion 2.14 or greater.


**Example Evacuate Server (evacuate Action)**

.. literalinclude:: ../../doc/api_samples/os-evacuate/server-evacuate-resp.json
   :language: javascript
