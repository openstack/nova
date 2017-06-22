.. -*- rst -*-

======================================================
 Servers Security Groups (servers, os-security-groups)
======================================================

Lists Security Groups for a server.

List Security Groups By Server
==============================

.. rest_method:: GET /servers/{server_id}/os-security-groups

Lists security groups for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id_path

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups_obj
  - description: description
  - id: security_group_id_body
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example List security groups by server**

.. literalinclude:: ../../doc/api_samples/os-security-groups/server-security-groups-list-resp.json
   :language: javascript
