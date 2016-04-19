.. -*- rst -*-

============================
 Quota sets (os-quota-sets)
============================

Permits administrators, depending on policy settings, to view default
quotas, view details for quotas, revert quotas to defaults, and update
the quotas for a project or a project and user.

Update Quotas
=============

.. rest_method:: PUT /v2.1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Update the quotas for a project or a project and a user.

You can force the update even if the quota has already been used and the reserved quota exceeds the new quota.

To force the update, specify the ``"force": "True"`` attribute in the request body. Default is ``false``. The following example request shows the optional ``force`` attribute.

To update a quota for a project and a user, specify the ``user_id`` query parameter.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - admin_tenant_id: admin_tenant_id
  - tenant_id: tenant_id
  - quota_set: quota_set
  - force: force
  - cores: cores
  - fixed_ips: fixed_ips
  - floating_ips: floating_ips
  - id: id
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules
  - security_groups: security_groups
  - server_groups: server_groups
  - server_group_members: server_group_members

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - user_id: user_id

**Example Update Quotas: JSON request**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quota-update-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips
  - floating_ips: floating_ips
  - id: id
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules
  - security_groups: security_groups
  - server_groups: server_groups
  - server_group_members: server_group_members

**Example Update Quotas: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quota-update-post-resp.json
   :language: javascript

Revert Quotas To Defaults
=========================

.. rest_method:: DELETE /v2.1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Reverts the quotas to default values for a project or a project and a user.

To revert quotas for a project and a user, specify the ``user_id`` query parameter.

Normal response codes: 202

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - admin_tenant_id: admin_tenant_id
  - tenant_id: tenant_id

Query Parameters
~~~~~~~~~~~~~~~~

.. rest_parameters:: parameters.yaml

  - user_id: user_id

Response
--------

Show A Quota
============

.. rest_method:: GET /v2.1/{admin_tenant_id}/os-quota-sets/{tenant_id}

Show the quota for a project or a project and a user.

In the request URI, you specify both the ID of the administrative project and the ID of the project for which you want to show quota.

To show a quota for a project and a user, specify the ``user_id`` query parameter.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - admin_tenant_id: admin_tenant_id
  - tenant_id: tenant_id

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips
  - floating_ips: floating_ips
  - id: id
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules
  - security_groups: security_groups
  - server_groups: server_groups
  - server_group_members: server_group_members

**Example Show A Quota: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/user-quotas-show-get-resp.json
   :language: javascript

List Default Quotas For Tenant
==============================

.. rest_method:: GET /v2.1/{admin_tenant_id}/os-quota-sets/{tenant_id}/defaults

Lists the default quotas for a project.

In the request URI, you specify both the ID of the administrative project and the ID of the project for which you want to show default quotas. These project IDs can match.

Normal response codes: 200

Error response codes: computeFault(400, 500), serviceUnavailable(503), badRequest(400),
unauthorized(401), forbidden(403), badMethod(405), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml

  - admin_tenant_id: admin_tenant_id
  - tenant_id: tenant_id

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_set: quota_set
  - cores: cores
  - fixed_ips: fixed_ips
  - floating_ips: floating_ips
  - id: id
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files
  - instances: instances
  - key_pairs: key_pairs
  - metadata_items: metadata_items
  - ram: ram
  - security_group_rules: security_group_rules
  - security_groups: security_groups
  - server_groups: server_groups
  - server_group_members: server_group_members

**Example List Default Quotas For Tenant: JSON response**

.. literalinclude:: ../../doc/api_samples/os-quota-sets/quotas-show-defaults-get-resp.json
   :language: javascript

