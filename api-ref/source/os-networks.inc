.. -*- rst -*-

========================
 Networks (os-networks)
========================

Creates, lists, shows information for, and deletes networks.

Adds network to a project, disassociates a network from a project, and
disassociates a project from a network.

Associates host with and disassociates host from a network.

Create Network
==============

.. rest_method:: POST /v2.1/{tenant_id}/os-networks

Creates a network.

Policy defaults enable only users with the administrative role or the owner of the server to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example Create Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks/network-create-req.json
   :language: javascript

Response
--------

**Example Create Network: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/network-create-resp.json
   :language: javascript

List Networks
=============

.. rest_method:: GET /v2.1/{tenant_id}/os-networks

Lists networks for the project.

Policy defaults enable all users to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

**Example List Networks: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/networks-list-resp.json
   :language: javascript

Add Network
===========

.. rest_method:: POST /v2.1/{tenant_id}/os-networks/add

Adds a network to a project.

Policy defaults enable only users with the administrative role to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example Add Network: JSON request**

.. literalinclude:: ../../doc/api_samples/os-networks/network-add-req.json
   :language: javascript

Response
--------

Show Network Details
====================

.. rest_method:: GET /v2.1/{tenant_id}/os-networks/{network_id}

Shows details for a network.

Policy defaults enable all users to perform this operation. Cloud providers can change these permissions through the ``policy.json`` file.

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

**Example Show Network Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-networks/network-show-resp.json
   :language: javascript

Delete Network
==============

.. rest_method:: DELETE /v2.1/{tenant_id}/os-networks/{network_id}

Deletes a network.

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

.. rest_method:: POST /v2.1/{tenant_id}/os-networks/{network_id}/action

Associates a network with a host.

Specify the ``associate_host`` action in the request body.

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

.. rest_method:: POST /v2.1/{tenant_id}/os-networks/{network_id}/action

Disassociates a host from a network.

Specify the ``disassociate_host`` action in the request body.

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

.. rest_method:: POST /v2.1/{tenant_id}/os-networks/{network_id}/action

Disassociates a network from a project. You can then reuse the network.

Specify the ``disassociate`` action in the request body.

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

.. rest_method:: POST /v2.1/{tenant_id}/os-networks/{network_id}/action

Disassociates a project from a network.

Specify the ``disassociate_project`` action in the request body.

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

