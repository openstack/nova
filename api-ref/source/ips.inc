.. -*- rst -*-

============================
 Servers IPs (servers, ips)
============================

Lists the IP addresses for an instance and shows details for an IP
address.

List Ips
========

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/ips

Lists IP addresses that are assigned to an instance.

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

**Example List Ips: JSON request**

.. literalinclude:: ../../doc/api_samples/ips/ips-resp.json
   :language: javascript

Show Ip Details
===============

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/ips/{network_label}

Shows IP addresses details for a network label of a server instance.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - network_label: network_label

Response
--------

**Example Show Ip Details: JSON request**

.. literalinclude:: ../../doc/api_samples/ips/ips-network-resp.json
   :language: javascript

