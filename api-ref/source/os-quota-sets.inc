.. -*- rst -*-

.. _os-quota-sets:

============================
 Quota sets (os-quota-sets)
============================

Permits administrators, depending on policy settings, to view default
quotas, view details for quotas, revert quotas to defaults, and update
the quotas for a project or a project and user.

Show A Quota
============

.. rest_method:: GET /os-quota-sets/{tenant_id}

Show the quota for a project or a project and a user.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

- 400 - BadRequest - the tenant_id is not valid in your cloud, perhaps
  because it was typoed.

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - user_id: user_id_query_quota

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips_quota
  - floating_ips: floating_ips
  - id: quota_tenant_or_user_id_body
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules_quota
  - security_groups: security_groups_quota
  - server_groups: server_groups
  - server_group_members: server_group_members
  - networks: networks_quota_set_optional

**Example Show A Quota: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/user-quotas-show-get-resp.json
   :language: javascript

Update Quotas
=============

.. rest_method:: PUT /os-quota-sets/{tenant_id}

Update the quotas for a project or a project and a user.

Users can force the update even if the quota has already been used and
the reserved quota exceeds the new quota. To force the update, specify
the ``"force": True`` attribute in the request body, the default value
is ``false``.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

- 400 - BadRequest - the tenant_id is not valid in your cloud, perhaps
  because it was typoed.

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - user_id: user_id_query_set_quota
  - quota_set: quota_set
  - force: force
  - cores: cores_quota_optional
  - fixed_ips: fixed_ips_quota_optional
  - floating_ips: floating_ips_quota_optional
  - injected_file_content_bytes: injected_file_content_bytes_quota_optional
  - injected_file_path_bytes: injected_file_path_bytes_quota_optional
  - injected_files: injected_files_quota_optional
  - instances: instances_quota_optional
  - key_pairs: key_pairs_quota_optional
  - metadata_items: metadata_items_quota_optional
  - ram: ram_quota_optional
  - security_group_rules: security_group_rules
  - security_groups: security_groups_quota_optional
  - server_groups: server_groups_quota_optional
  - server_group_members: server_group_members_quota_optional
  - networks: networks_quota_set_optional

**Example Update Quotas: JSON request**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-update-post-req.json
   :language: javascript

**Example Update Quotas with the optional ``force`` attribute: JSON request**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-update-force-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips_quota
  - floating_ips: floating_ips
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules_quota
  - security_groups: security_groups_quota
  - server_groups: server_groups
  - server_group_members: server_group_members
  - networks: networks_quota_set_optional

**Example Update Quotas: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-update-post-resp.json
   :language: javascript

Revert Quotas To Defaults
=========================

.. rest_method:: DELETE /os-quota-sets/{tenant_id}

Reverts the quotas to default values for a project or a project and a user.

To revert quotas for a project and a user, specify the ``user_id`` query parameter.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - user_id: user_id_query_quota_delete

Response
--------

There is no body content for the response of a successful DELETE operation.

List Default Quotas For Tenant
==============================

.. rest_method:: GET /os-quota-sets/{tenant_id}/defaults

Lists the default quotas for a project.

Normal response codes: 200

Error response codes: badrequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips_quota
  - floating_ips: floating_ips
  - id: quota_tenant_or_user_id_body
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules_quota
  - security_groups: security_groups_quota
  - server_groups: server_groups
  - server_group_members: server_group_members
  - networks: networks_quota_set_optional

**Example List Default Quotas For Tenant: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-show-defaults-get-resp.json
   :language: javascript

Show The Detail of Quota
========================

.. rest_method:: GET /os-quota-sets/{tenant_id}/detail

Show the detail of quota for a project or a project and a user.

To show a quota for a project and a user, specify the ``user_id`` query parameter.

Normal response codes: 200

Error response codes: badrequest(400), unauthorized(401), forbidden(403)

- 400 - BadRequest - the {tenant_id} is not valid in your cloud, perhaps
  because it was typoed.

Request
-------

.. rest_parameters:: parameters.yaml

  - tenant_id: tenant_id
  - user_id: user_id_query_quota

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores_quota_details
  - fixed_ips: fixed_ips_quota_details
  - floating_ips: floating_ips_quota_details
  - id: quota_tenant_or_user_id_body
  - injected_file_content_bytes: injected_file_content_bytes_quota_details
  - injected_file_path_bytes: injected_file_path_bytes_quota_details
  - injected_files: injected_files_quota_details
  - instances: instances_quota_details
  - key_pairs: key_pairs_quota_details
  - metadata_items: metadata_items_quota_details
  - ram: ram_quota_details
  - security_group_rules: security_group_rules_quota_details
  - security_groups: security_groups_quota_details
  - server_groups: server_groups_quota_details
  - server_group_members: server_group_members_quota_details
  - networks: networks_quota_set_optional

**Example Show A Quota: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-show-detail-get-resp.json
   :language: javascript
