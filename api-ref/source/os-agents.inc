.. -*- rst -*-

==========================
 Guest agents (os-agents)
==========================

Creates, lists, updates, and deletes guest agent builds. Use guest
agents to access files on the disk, configure networking, or run other
applications or scripts in the guest while the agent runs. This
hypervisor-specific extension is not currently enabled for KVM. Use of
guest agents is possible only if the underlying service provider uses
the Xen driver.

Create Agent Build
==================

.. rest_method:: POST /v2.1/{tenant_id}/os-agents

Creates an agent build.

Normal response codes: 201

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

**Example Create Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-create-req.json
   :language: javascript

Response
--------

**Example Create Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-create-resp.json
   :language: javascript

List Agent Builds
=================

.. rest_method:: GET /v2.1/{tenant_id}/os-agents

Lists agent builds.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - agent_id: agent_id
  - architecture: architecture
  - hypervisor: hypervisor
  - url: url
  - md5hash: md5hash
  - version: version

Response
--------

**Example List Agent Builds: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agents-list-resp.json
   :language: javascript

Delete Agent Build
==================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-agents

Deletes an existing agent build.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

Update Agent Build
==================

.. rest_method:: PUT /v2.1/{tenant_id}/os-agents/{agent_build_id}

Updates an agent build.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - agent_build_id: agent_build_id
  - url: url
  - md5hash: md5hash
  - version: version

**Example Update Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-update-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - agent_id: agent_id
  - url: url
  - md5hash: md5hash
  - version: version

**Example Update Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-update-resp.json
   :language: javascript

