.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

====================================================
 Rules for security group (os-security-group-rules)
====================================================

Creates and deletes security group rules.

Create Security Group Rule
==========================

.. rest_method:: POST /v2.1/{tenant_id}/os-security-group-rules

Creates a rule for a security group.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_rule: security_group_rule
  - parent_group_id: parent_group_id
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - cidr: cidr
  - group_id: group_id

.. TODO(sdague): we currently have no samples here
   **Example Create security group rule: JSON request**

   .. literalinclude:: ../../doc/api_samples/os-security-group-rules/security-group-rule-create-req.json
      :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - security_group_rule: security_group_rule
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - ip_range: ip_range
  - cidr: cidr
  - id: id
  - group: group
  - parent_group_id: parent_group_id
  - name: name

.. TODO(sdague): we currently have no samples here
   **Example Create security group rule: JSON response**

   .. literalinclude:: ../../doc/api_samples/os-security-group-rules/security-group-rule-create-resp.json
      :language: javascript

Delete Security Group Rule
==========================

.. rest_method:: DELETE /v2.1/{tenant_id}/os-security-group-rules/{security_group_rule_id}

Deletes a security group rule.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - security_group_rule_id: security_group_rule_id

Response
--------

There is no body content for the response of a successful DELETE query.
