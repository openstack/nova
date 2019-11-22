.. -*- rst -*-

====================================================================
 Rules for default security group (os-security-group-default-rules)
====================================================================

.. warning::

   This API only available with ``nova-network`` which is
   deprecated. It should be avoided in any new applications.
   These will fail with a 404 starting from microversion 2.36.
   They were completely removed in the 21.0.0 (Ussuri) release.

Lists, shows information for, and creates default security group rules.

List Default Security Group Rules
=================================

.. rest_method:: GET /os-security-group-default-rules

Lists default security group rules.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
gone(410), notImplemented(501)

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group_default_rules: security_group_default_rules
  - from_port: from_port
  - id: secgroup_default_rule_id
  - ip_protocol: ip_protocol
  - ip_range: secgroup_rule_ip_range
  - ip_range.cidr: secgroup_rule_cidr
  - to_port: to_port

**Example List default security group rules: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-list-resp.json
   :language: javascript

Show Default Security Group Rule Details
========================================

.. rest_method:: GET /os-security-group-default-rules/{security_group_default_rule_id}

Shows details for a security group rule.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_default_rule_id: security_group_default_rule_id

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group_default_rule: security_group_default_rule
  - from_port: from_port
  - id: secgroup_default_rule_id
  - ip_protocol: ip_protocol
  - ip_range: secgroup_rule_ip_range
  - ip_range.cidr: secgroup_rule_cidr
  - to_port: to_port

**Example Show default security group rule: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-show-resp.json
   :language: javascript

Create Default Security Group Rule
==================================

.. rest_method:: POST /os-security-group-default-rules

Creates a default security group rule.

If you specify a source port ( ``from_port`` ) or destination port ( ``to_port`` ) value, you must specify an
IP protocol ( ``ip_protocol`` ) value. Otherwise, the operation returns the ``Bad Request (400)`` response code.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
conflict(409), gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_default_rule: security_group_default_rule
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - cidr: secgroup_rule_cidr

**Example Create default security group rule: JSON request**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-create-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group_default_rule: security_group_default_rule
  - from_port: from_port
  - id: secgroup_default_rule_id
  - ip_protocol: ip_protocol
  - ip_range: secgroup_rule_ip_range
  - ip_range.cidr: secgroup_rule_cidr
  - to_port: to_port

**Example Create default security group rule: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-group-default-rules/security-group-default-rules-create-resp.json
   :language: javascript

Delete Default Security Group Rule
==================================

.. rest_method:: DELETE /os-security-group-default-rules/{security_group_default_rule_id}

Deletes a security group rule.

Normal response codes: 204

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), gone(410), notImplemented(501)

Request
-------

.. rest_parameters:: parameters.yaml

  - security_group_default_rule_id: security_group_default_rule_id

Response
--------
