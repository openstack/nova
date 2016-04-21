.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=======================================
 Bare metal nodes (os-baremetal-nodes)
=======================================

Bare metal nodes.


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

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-list-resp.json
   :language: javascript

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

.. literalinclude:: ../../doc/api_samples/os-baremetal-nodes/baremetal-node-get-resp.json
   :language: javascript
