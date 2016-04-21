.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==========================
 Fixed IPs (os-fixed-ips)
==========================

Shows data for a fixed IP, such as host name, CIDR, and address. Also,
reserves and frees a fixed IP address.

Show Fixed Ip Details
=====================

.. rest_method:: GET /v2.1/{tenant_id}/os-fixed-ips/{fixed_ip}

Shows details for a fixed IP address.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - fixed_ip: fixed_ip

Response
--------

**Example Show Fixed Ip Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-fixed-ips/fixedips-get-resp.json
   :language: javascript

Reserve Or Release A Fixed Ip
=============================

.. rest_method:: POST /v2.1/{tenant_id}/os-fixed-ips/{fixed_ip}/action

Reserves or releases a fixed IP.

To reserve a fixed IP address, specify ``reserve`` in the request body. To release a fixed IP address, specify ``unreserve`` in the request body.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - fixed_ip: fixed_ip

**Example Reserve Or Release A Fixed Ip: JSON request**

.. literalinclude:: ../../doc/api_samples/os-fixed-ips/fixedip-post-req.json
   :language: javascript

Response
--------

