.. -*- rst -*-

============================
 Servers IPs (servers, ips)
============================

Lists the IP addresses for an instance and shows details for an IP
address.

List Ips
========

.. rest_method:: GET /servers/{server_id}/ips

Lists IP addresses that are assigned to an instance.

Policy defaults enable only users with the administrative role or the owner of
the server to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - addresses: addresses_obj
  - network_label: network_label_body
  - addr: ip_address
  - version: version_ip

**Example List Ips**

.. literalinclude:: ../../doc/api_samples/server-ips/server-ips-resp.json
   :language: javascript

Show Ip Details
===============

.. rest_method:: GET /servers/{server_id}/ips/{network_label}

Shows IP addresses details for a network label of a server instance.

Policy defaults enable only users with the administrative role or the owner of
the server to perform this operation. Cloud providers can change these
permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path
  - network_label: network_label

Response
--------

.. rest_parameters:: parameters.yaml

  - network_label: network_label_body
  - addr: ip_address
  - version: version_ip

**Example Show Ip Details**

.. literalinclude:: ../../doc/api_samples/server-ips/server-ips-network-resp.json
   :language: javascript
