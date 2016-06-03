.. -*- rst -*-
.. needs:body_verification

=================
 Limits (limits)
=================

Shows rate and absolute limits for the tenant.

Show Rate And Absolute Limits
=============================

.. rest_method:: GET /limits

Shows rate and absolute limits for the tenant.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Response
--------

.. rest_parameters:: parameters.yaml

  - limits: limits
  - absolute: limits_absolutes
  - maxImageMeta: metadata_items
  - maxPersonality: injected_files
  - maxPersonalitySize: injected_file_content_bytes
  - maxSecurityGroupRules: security_group_rules
  - maxSecurityGroups: security_groups
  - maxServerGroupMembers: server_group_members
  - maxServerGroups: server_groups
  - maxServerMeta: metadata_items
  - maxTotalCores: cores
  - maxTotalFloatingIps: floating_ips
  - maxTotalInstances: instances
  - maxTotalKeypairs: key_pairs
  - maxTotalRAMSize: ram
  - rate: limits_rates

**Example Show Rate And Absolute Limits: JSON response**

.. literalinclude:: ../../doc/api_samples/limits/limit-get-resp.json
   :language: javascript
