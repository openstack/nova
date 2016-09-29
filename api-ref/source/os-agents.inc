.. -*- rst -*

==========================
 Guest agents (os-agents)
==========================

Creates, lists, updates, and deletes guest agent builds. Use guest
agents to access files on the disk, configure networking, or run other
applications or scripts in the guest while the agent is running. This
hypervisor-specific extension is currently only for the Xen driver. Use of
guest agents is possible only if the underlying service provider uses
the Xen driver.

List Agent Builds
=================

.. rest_method:: GET /os-agents

Lists agent builds.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - hypervisor: hypervisor_query


Response
--------

.. rest_parameters:: parameters.yaml

  - agents: agents
  - agent_id: agent_id
  - architecture: architecture
  - hypervisor: hypervisor_type
  - md5hash: md5hash
  - os: os
  - url: url
  - version: version

**Example List Agent Builds: JSON response**

.. literalinclude:: ../../doc/api_samples/os-agents/agents-get-resp.json
   :language: javascript

Create Agent Build
==================

.. rest_method:: POST /os-agents

Creates an agent build.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - agent: agent
  - hypervisor: hypervisor_type
  - os: os
  - architecture: architecture
  - version: version
  - md5hash: md5hash
  - url: url

**Example Create Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - agent: agent
  - agent_id: agent_id
  - architecture: architecture
  - hypervisor: hypervisor_type
  - md5hash: md5hash
  - os: os
  - url: url
  - version: version

**Example Create Agent Build: JSON response**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-post-resp.json
   :language: javascript

Update Agent Build
==================

.. rest_method:: PUT /os-agents/{agent_build_id}

Updates an agent build.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - agent_build_id: agent_build_id
  - para: para
  - url: url
  - md5hash: md5hash
  - version: version

**Example Update Agent Build: JSON request**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-update-put-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - agent: agent
  - agent_id: agent_id_str
  - md5hash: md5hash
  - url: url
  - version: version

**Example Update Agent Build: JSON response**

.. literalinclude:: ../../doc/api_samples/os-agents/agent-update-put-resp.json
   :language: javascript

Delete Agent Build
==================

.. rest_method:: DELETE /os-agents/{agent_build_id}

Deletes an existing agent build.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - agent_build_id: agent_build_id

Response
--------

There is no body content for the response of a successful DELETE query
