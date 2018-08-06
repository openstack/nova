.. -*- rst -*-

==================================
 Server groups (os-server-groups)
==================================

Lists, shows information for, creates, and deletes server groups.

List Server Groups
==================

.. rest_method:: GET /os-server-groups

Lists all server groups for the tenant.

Administrative users can use the ``all_projects`` query parameter to list all server groups for all projects.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - all_projects: all_projects
  - limit: limit_simple
  - offset: offset_simple

Response
--------

.. rest_parameters:: parameters.yaml

  - server_groups: server_groups_list
  - id: server_group_id_body
  - name: name_server_group
  - policies: policies
  - members: members
  - metadata: metadata_server_group_max_2_63
  - project_id: project_id_server_group
  - user_id: user_id_server_group
  - policy: policy_name
  - rules: policy_rules

**Example List Server Groups (2.64): JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/v2.64/server-groups-list-resp.json
   :language: javascript

Create Server Group
===================

.. rest_method:: POST /os-server-groups

Creates a server group.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_group: server_group
  - name: name_server_group
  - policies: policies
  - policy: policy_name
  - rules: policy_rules_optional

**Example Create Server Group (2.64): JSON request**

.. literalinclude:: ../../doc/api_samples/os-server-groups/v2.64/server-groups-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - server_group: server_group
  - id: server_group_id_body
  - name: name_server_group
  - policies: policies
  - members: members
  - metadata: metadata_server_group_max_2_63
  - project_id: project_id_server_group
  - user_id: user_id_server_group
  - policy: policy_name
  - rules: policy_rules

**Example Create Server Group (2.64): JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/v2.64/server-groups-post-resp.json
   :language: javascript

Show Server Group Details
=========================

.. rest_method:: GET /os-server-groups/{server_group_id}

Shows details for a server group.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_group_id: server_group_id

Response
--------

.. rest_parameters:: parameters.yaml

  - server_group: server_group
  - id: server_group_id_body
  - name: name_server_group
  - policies: policies
  - members: members
  - metadata: metadata_server_group_max_2_63
  - project_id: project_id_server_group
  - user_id: user_id_server_group
  - policy: policy_name
  - rules: policy_rules

**Example Show Server Group Details (2.64): JSON response**

.. literalinclude:: ../../doc/api_samples/os-server-groups/v2.64/server-groups-get-resp.json
   :language: javascript

Delete Server Group
===================

.. rest_method:: DELETE /os-server-groups/{server_group_id}

Deletes a server group.

Normal response codes: 204

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_group_id: server_group_id

Response
--------

There is no body content for the response of a successful DELETE action.
