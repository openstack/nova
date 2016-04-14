.. -*- rst -*-

=========================================
 Port interfaces (servers, os-interface)
=========================================

Creates a port interface and uses it to attach a port to a server and
detaches a port interface from a server. Also, lists all port interfaces
and shows details for a port interface.

Create Interface
================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/os-interface

Creates a port interface and uses it to attach a port to a server instance.

Normal response codes: 200,,503,400,401,403,405,415,400

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - interfaceAttachment: interfaceAttachment
  - port_id: port_id
  - net_id: net_id
  - fixed_ips: fixed_ips

**Example Create Interface: JSON request**

.. literalinclude:: ../../doc/api_samples/os-interface/port-interface-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - interfaceAttachment: interfaceAttachment
  - fixed_ips: fixed_ips
  - mac_addr: mac_addr
  - net_id: net_id
  - port_id: port_id
  - port_state: port_state

**Example Create Interface: JSON request**

.. literalinclude:: ../../doc/api_samples/os-interface/port-interface-create-resp.json
   :language: javascript

List Port Interfaces
====================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-interface

Lists port interfaces that are attached to a server.

Normal response codes: 200,,503,400,401,403,405,404

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

  - interfaceAttachment: interfaceAttachment
  - port_state: port_state
  - fixed_ips: fixed_ips
  - mac_addr: mac_addr
  - net_id: net_id
  - port_id: port_id

**Example List Port Interfaces: JSON request**

.. literalinclude:: ../../doc/api_samples/os-interface/port-interfaces-list-resp.json
   :language: javascript

Show Port Interface Details
===========================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-interface/{port_id}

Shows details for a port interface that is attached to a server.

Normal response codes: 200,,503,400,401,403,405,404

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - port_id: port_id

Response
--------

**Example Show Port Interface Details: JSON request**

.. literalinclude:: ../../doc/api_samples/os-interface/port-interface-show-resp.json
   :language: javascript

Detach Interface
================

.. rest_method:: DELETE /v2.1/{tenant_id}/servers/{server_id}/os-interface/{port_id}

Detaches a port interface.

Normal response codes: 202,,503,400,401,403,405,415,400

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - port_id: port_id

Response
--------

