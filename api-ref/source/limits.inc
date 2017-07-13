.. -*- rst -*-

=================
 Limits (limits)
=================

Shows rate and absolute limits for the project.

Show Rate And Absolute Limits
=============================

.. rest_method:: GET /limits

Shows rate and absolute limits for the project.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - reserved: reserved_query
  - tenant_id: tenant_id_query

Response
--------

.. rest_parameters:: parameters.yaml

  - limits: limits
  - absolute: limits_absolutes
  - maxImageMeta: image_metadata_items
  - maxPersonality: injected_files
  - maxPersonalitySize: injected_file_content_bytes
  - maxSecurityGroupRules: security_group_rules_quota
  - maxSecurityGroups: security_groups_quota
  - maxServerGroupMembers: server_group_members
  - maxServerGroups: server_groups
  - maxServerMeta: metadata_items
  - maxTotalCores: cores
  - maxTotalFloatingIps: floating_ips
  - maxTotalInstances: instances
  - maxTotalKeypairs: key_pairs
  - maxTotalRAMSize: ram
  - totalCoresUsed: total_cores_used
  - totalFloatingIpsUsed: total_floatingips_used
  - totalInstancesUsed: total_instances_used
  - totalRAMUsed: total_ram_used
  - totalSecurityGroupsUsed: total_security_groups_used
  - totalServerGroupsUsed: total_server_groups_used
  - rate: limits_rates

**Example Show Rate And Absolute Limits: JSON response**

.. literalinclude:: ../../doc/api_samples/limits/limit-get-resp.json
   :language: javascript
