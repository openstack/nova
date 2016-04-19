.. -*- rst -*-

====================================================================
 Rules for default security group (os-security-group-default-rules)
====================================================================

Lists, shows information for, and creates default security group rules.

List Default Security Group Rules
=================================

.. rest_method:: GET /v2.1/{tenant_id}/os-security-group-default-rules

Lists default security group rules.

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

  - from_port: from_port
  - id: id
  - ip_protocol: ip_protocol
  - ip_range: ip_range
  - cidr: cidr
  - to_port: to_port

**Example List default security group rules: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-list-resp.json
   :language: javascript

Create Default Security Group Rule
==================================

.. rest_method:: POST /v2.1/{tenant_id}/os-security-group-default-rules

Creates a default security group rule.

If you specify a source port ( ``from_port`` ) or destination port ( ``to_port`` ) value, you must specify an IP protocol ( ``ip_protocol`` ) value. Otherwise, the operation returns the ``Bad Request (400)`` response code.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - id: id
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - cidr: cidr

**Example Create default security group rule: JSON request**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - from_port: from_port
  - id: id
  - ip_protocol: ip_protocol
  - ip_range: ip_range
  - cidr: cidr
  - to_port: to_port

**Example Create default security group rule: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-create-resp.json
   :language: javascript

Show Default Security Group Rule Details
========================================

.. rest_method:: GET /v2.1/{tenant_id}/os-security-group-default-rules/{security_group_default_rule_id}

Shows details for a security group rule.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_default_rule_id: security_group_default_rule_id

Response
--------

.. rest_parameters:: parameters.yaml

  - from_port: from_port
  - id: id
  - ip_protocol: ip_protocol
  - ip_range: ip_range
  - cidr: cidr
  - to_port: to_port

**Example Show default security group rule: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-show-resp.json
   :language: javascript

Delete Default Security Group Rule
==================================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-security-group-default-rules/{security_group_default_rule_id}

Deletes a security group rule.

Normal response codes: 204

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_default_rule_id: security_group_default_rule_id

Response
--------
