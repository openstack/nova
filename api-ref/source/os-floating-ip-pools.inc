.. -*- rst -*-

==========================================
 Floating IP pools (os-floating-ip-pools)
==========================================

Manages groups of floating IPs.

List Floating Ip Pools
======================

.. rest_method:: GET /v2.1/{tenant_id}/os-floating-ip-pools

Lists floating IP pools.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
^^^^^^^

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
^^^^^^^^

.. rest_parameters:: parameters.yaml

  - floating_ip_pools: floating_ip_pools
  - name: name

**Example List Floating Ip Pools: JSON request**

.. literalinclude:: ../../doc/api_samples/os-floating-ip-pools/floatingippools-list-resp.json
   :language: javascript

