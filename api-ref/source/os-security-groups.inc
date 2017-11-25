.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

==================================================
 Security groups (os-security-groups) (DEPRECATED)
==================================================

.. warning::

   These APIs are proxy calls to the Network service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Network APIs
   <https://developer.openstack.org/api-ref/networking/v2/#security-groups-security-groups>`__.

Lists, shows information for, creates, updates and deletes security groups.

List Security Groups
====================

.. rest_method:: GET /os-security-groups

Lists security groups.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - limit: limit_simple
  - offset: offset_simple
  - all_tenants: all_tenants_sec_grp_query

Response
--------

.. rest_parameters:: parameters.yaml

  - security_groups: security_groups_obj
  - description: description
  - id: security_group_id_body
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
  - id: security_group_id_body
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
  - id: security_group_id_body
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
  - id: security_group_id_body
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
