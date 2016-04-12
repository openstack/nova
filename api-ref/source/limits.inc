.. -*- rst -*-

=================
 Limits (limits)
=================

Shows rate and absolute limits for the tenant.

Show Rate And Absolute Limits
=============================

.. rest_method:: GET /v2.1/{tenant_id}/limits

Shows rate and absolute limits for the tenant.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
^^^^^^^^

**Example Show Rate And Absolute Limits: JSON request**

.. literalinclude:: ../../doc/api_samples/limits/limits-get-resp.json
   :language: javascript

