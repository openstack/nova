.. -*- rst -*-

=======================================
 Project networks (os-tenant-networks)
=======================================

Creates, lists, shows information for, and deletes project networks.

Create Project Network
======================

.. rest_method:: POST /v2.1/{tenant_id}/os-tenant-networks

Creates a project network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example Create Project Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-req.json
   :language: javascript

Response
--------

**Example Create Project Network: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-res.json
   :language: javascript

List Project Networks
=====================

.. rest_method:: GET /v2.1/{tenant_id}/os-tenant-networks

Lists all project networks.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Project Networks: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-list-res.json
   :language: javascript

Show Project Network Details
============================

.. rest_method:: GET /v2.1/{tenant_id}/os-tenant-networks/{network_id}

Shows details for a project network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

Response
--------

**Example Show Project Network Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-tenant-networks/networks-post-res.json
   :language: javascript

Delete Project Network
======================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-tenant-networks/{network_id}

Deletes a project network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

Response
--------

Associate Host
==============

.. rest_method:: POST /v2.1/{tenant_id}/os-tenant-networks/{network_id}/action

Associates a network with a host.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

**Example Associate Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-associate-host-req.json
   :language: javascript

Response
--------

Disassociate Host
=================

.. rest_method:: POST /v2.1/{tenant_id}/os-tenant-networks/{network_id}/action

Disassociates a host from a network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

**Example Disassociate Host: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-disassociate-host-req.json
   :language: javascript

Response
--------

Disassociate Network
====================

.. rest_method:: POST /v2.1/{tenant_id}/os-tenant-networks/{network_id}/action

Disassociates a network from a project so that the network can be reused.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

**Example Disassociate Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks/networks-disassociate-req.json
   :language: javascript

Response
--------

Disassociate Project
====================

.. rest_method:: POST /v2.1/{tenant_id}/os-tenant-networks/{network_id}/action

Disassociates a project from a network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - network_id: network_id

**Example Disassociate Project: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks-associate/network-disassociate-project-req.json
   :language: javascript

Response
--------
