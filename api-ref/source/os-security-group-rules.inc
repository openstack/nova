.. -*- rst -*-

================================================================
 Rules for security group (os-security-group-rules) (DEPRECATED)
================================================================

.. warning::

   These APIs are proxy calls to the Network service. Nova has
   deprecated all the proxy APIs and users should use the native APIs
   instead. These will fail with a 404 starting from microversion 2.36.
   See: `Relevant Network APIs
   <https://docs.openstack.org/api-ref/network/v2/#security-group-rules-security-group-rules>`__.

Creates and deletes security group rules.

Create Security Group Rule
==========================

.. rest_method:: POST /os-security-group-rules

Creates a rule for a security group. Either ``cidr`` or ``group_id`` must be
specified when creating a rule.

.. note::
    nova-network only supports ingress rules. If you want to define egress
    rules you must use the Neutron networking service.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml


  - security_group_rule: security_group_rule
  - parent_group_id: parent_group_id
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - cidr: secgroup_rule_cidr
  - group_id: group_id

**Example Create security group rule: JSON request**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-rules-post-req.json
   :language: javascript

Response
--------

The ``group`` is empty if ``group_id`` was not provided on the request.

The ``ip_range`` is empty if ``cidr`` was not provided on the request.

.. rest_parameters:: parameters.yaml

  - security_group_rule: security_group_rule
  - ip_protocol: ip_protocol
  - from_port: from_port
  - to_port: to_port
  - ip_range: secgroup_rule_ip_range
  - ip_range.cidr: secgroup_rule_cidr
  - id: secgroup_rule_id
  - parent_group_id: parent_group_id
  - group: group
  - group.name: name_sec_group_optional
  - group.tenant_id: secgroup_tenant_id_body

**Example Create security group rule: JSON response**

.. literalinclude:: ../../doc/api_samples/os-security-groups/security-group-rules-post-resp.json
   :language: javascript

Delete Security Group Rule
==========================

.. rest_method:: DELETE /os-security-group-rules/{security_group_rule_id}

Deletes a security group rule.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - security_group_rule_id: security_group_rule_id

Response
--------

There is no body content for the response of a successful DELETE query.
