.. -*- rst -*-

=============================================================
 Servers virtual interfaces (servers, os-virtual-interfaces)
=============================================================

Lists virtual interfaces for a server instance.

List Virtual Interfaces
=======================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-virtual-interfaces

Lists the virtual interfaces for an instance.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Change these permissions through the ``policy.json`` file.

The API v2 returns the network ID in the ``OS-EXT-VIF-NET:net_id`` response attribute.

The API v2.1 base version does not return the network ID.

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

.. rest_parameters:: parameters.yaml

  - virtual_interfaces: virtual_interfaces
  - id: virtual_interface_id
  - mac_address: mac_address

**Example List Virtual Interfaces: JSON response**

.. literalinclude:: ../../doc/api_samples/os-virtual-interfaces/vifs-list-resp.json
   :language: javascript

