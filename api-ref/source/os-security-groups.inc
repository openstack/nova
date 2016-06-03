.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

======================================
 Security groups (os-security-groups)
======================================

Lists, shows information for, creates, updates and deletes security groups.

List Security Groups
====================

.. rest_method:: GET /os-security-groups

Lists security groups.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example List security groups: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-list-get-resp.json
   :language: javascript

Create Security Group
=====================

.. rest_method:: POST /os-security-groups

Creates a security group.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group: security_group
  - name: name
  - description: description

**Example Create security group: JSON request**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group: security_group
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example Create security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-create-resp.json
   :language: javascript

Show Security Group Details
===========================

.. rest_method:: GET /os-security-groups/{security_group_id}

Shows details for a security group.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_id: security_group_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group: security_group
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example Show security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-get-resp.json
   :language: javascript

Update Security Group
=====================

.. rest_method:: PUT /os-security-groups/{security_group_id}

Updates a security group.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_id: security_group_id
  - name: name
  - description: description

**Example Update security group: JSON request**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group: security_group
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example Update security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-create-resp.json
   :language: javascript

Delete Security Group
=====================

.. rest_method:: DELETE /os-security-groups/{security_group_id}

Deletes a security group.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_id: security_group_id

Response
--------

There is no body content for the response of a successful DELETE query.

List Security Groups By Server
==============================

.. rest_method:: GET /servers/{server_id}/os-security-groups

Lists security groups for a server.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - server_id: server_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id_body


**Example List security groups by server: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/server-security-groups-list-resp.json
   :language: javascript
