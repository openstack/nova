.. -*- rst -*-
.. needs:method_verification
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

======================================
 Security groups (os-security-groups)
======================================

Lists, shows information for, creates, and deletes security groups.

List Security Groups
====================

.. rest_method:: GET /v2.1/{tenant_id}/os-security-groups

Lists security groups.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id

**Example List security groups: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-list-get-resp.json
   :language: javascript

Create Security Group
=====================

.. rest_method:: POST /v2.1/{tenant_id}/os-security-groups

Creates a security group.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
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
  - tenant_id: tenant_id

**Example Create security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-create-resp.json
   :language: javascript

Show Security Group Details
===========================

.. rest_method:: GET /v2.1/{tenant_id}/os-security-groups/{security_group_id}

Shows details for a security group.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_id: security_group_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group: security_group
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id

**Example Show security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-get-resp.json
   :language: javascript

Update Security Group
=====================

.. rest_method:: PUT /v2.1/{tenant_id}/os-security-groups/{security_group_id}

Updates a security group.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
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
  - tenant_id: tenant_id

**Example Update security group: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-create-resp.json
   :language: javascript

Delete Security Group
=====================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-security-groups/{security_group_id}

Deletes a security group.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_id: security_group_id

Response
--------

List Security Groups By Server
==============================

.. rest_method:: GET /v2.1/{tenant_id}/servers/{server_id}/os-security-groups

Lists security groups for a server.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - server_id: server_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups
  - description: description
  - id: id
  - name: name
  - rules: rules
  - tenant_id: tenant_id

**Example List security groups by server: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-groups-list-get-resp.json
   :language: javascript
