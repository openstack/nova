.. -*- rst -*-

=======================================
 Bare metal nodes (os-baremetal-nodes)
=======================================

Bare metal nodes.

Add Bare Metal Node
===================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes

Adds a bare metal node to a server.

Preconditions

You can add a bare metal node to a server with an ``ACTIVE``, ``PAUSED``, ``SHUTOFF``, ``VERIFY_RESIZE``, or ``SOFT_DELETED`` status.

You can add a bare metal node to a server with a status that is not locked.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Add Bare Metal Node: JSON request**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-create-req.json
   :language: javascript

**Example Add Bare Metal Node: JSON request**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-create-with-address-req.json
   :language: javascript

Response
--------

**Example Add Bare Metal Node: JSON response**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-create-resp.json
   :language: javascript

**Example Add Bare Metal Node: JSON request**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-create-with-address-resp.json
   :language: javascript

List Bare Metal Nodes
=====================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes

Lists the bare metal nodes that are associated with a server.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
--------

**Example List Bare Metal Nodes: JSON response**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-nodes-list-resp.json
   :language: javascript

Add Interface To Bare Metal Node
================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes/action

Adds an interface to a bare metal node that is associated with a server.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Add Interface To Bare Metal Node: JSON request**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-add-interface-req.json
   :language: javascript

Response
--------

**Example Add Interface To Bare Metal Node: JSON response**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-add-interface-resp.json
   :language: javascript

Delete Interface From Bare Metal Node
=====================================

.. rest_method:: POST /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes/action

Deletes an interface from a bare metal node that is associated with a server.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

**Example Delete Interface From Bare Metal Node: JSON request**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-remove-interface-req.json
   :language: javascript

Response
--------

Show Bare Metal Node Details
============================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes/{node_id}

Shows details for a bare metal node.

Preconditions

The bare metal node must be associated with the server.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - node_id: node_id

Response
--------

**Example Show Bare Metal Node Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-show-resp.json
   :language: javascript

Delete Bare Metal Node
======================

.. rest_method:: DELETE /v2.1/{tenant_id}/servers/{server_id}/os-baremetal-nodes/{node_id}

Deletes a bare metal node from a server.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id
  - node_id: node_id

Response
--------

