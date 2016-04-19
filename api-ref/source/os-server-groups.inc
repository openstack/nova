.. -*- rst -*-

==================================
 Server groups (os-server-groups)
==================================

Lists, shows information for, creates, and deletes server groups.

List Server Groups
==================

.. rest_method:: GET /v2.1/{tenant_id}/os-server-groups

Lists all server groups for the tenant.

Administrative users can use the ``all_projects`` query parameter to list all server groups for all projects.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - all_projects: all_projects

Response
--------

.. rest_parameters:: parameters.yaml

  - server_groups: server_groups
  - id: id
  - name: name
  - policies: policies
  - members: members
  - metadata: metadata
  - project_id: project_id
  - user_id: user_id

**Example List Server Groups: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/server-groups-list-resp.json
   :language: javascript

Create Server Group
===================

.. rest_method:: POST /v2.1/{tenant_id}/os-server-groups

Creates a server group.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - name: name
  - policies: policies

**Example Create Server Group: JSON request**

.. literalinclude:: ../../doc/api_samples/os-server-groups/server-group-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - server_groups: server_groups
  - id: id
  - name: name
  - policies: policies
  - members: members
  - metadata: metadata
  - project_id: project_id
  - user_id: user_id

**Example Create Server Group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/server-group-create-resp.json
   :language: javascript

Show Server Group Details
=========================

.. rest_method:: GET /v2.1/{tenant_id}/os-server-groups/{server_group_id}

Shows details for a server group.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_group_id: server_group_id

Response
--------

.. rest_parameters:: parameters.yaml

  - server_groups: server_groups
  - id: id
  - name: name
  - policies: policies
  - members: members
  - metadata: metadata
  - project_id: project_id
  - user_id: user_id

**Example Show Server Group Details: JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/server-group-show-resp.json
   :language: javascript

Delete Server Group
===================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-server-groups/{server_group_id}

Deletes a server group.

Normal response codes: 204,,503,400,401,403,405,404

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_group_id: server_group_id

Response
--------

