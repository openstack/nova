.. -*- rst -*-

=======================================
 Quota class sets (os-quota-class-sets)
=======================================

Show, Create or Update the quotas for a Quota Class.
Nova supports implicit 'default' Quota Class only.

.. note::
    Once a default limit is set via the ``default`` quota class via the API,
    that takes precedence over any changes to that resource limit in the
    configuration options. In other words, once you've changed things via
    the API, you either have to keep those synchronized with the configuration
    values or remove the default limit from the database manually as there is
    no REST API for removing quota class values from the database.

    For Example: If you updated default quotas for instances, to 20, but
    didn't change ``quota_instances`` in your ``nova.conf``, you'd now
    have default quota for instances as 20 for all projects.
    If you then change ``quota_instances=5`` in nova.conf, but didn't
    update the ``default`` quota class via the API, you'll still have
    a default quota of 20 for instances regardless of ``nova.conf``.
    Refer: `Quotas
    <https://docs.openstack.org/nova/latest/user/quotas.html>`__
    for more details.

.. warning::
    There is a bug in the v2.1 API until microversion 2.49 and
    the legacy v2 compatible API which does not return the
    ``server_groups`` and ``server_group_members`` quotas in
    GET and PUT ``os-quota-class-sets`` API response, whereas the v2 API
    used to return those keys in the API response.
    There is workaround to get the ``server_groups`` and
    ``server_group_members`` quotas using
    "List Default Quotas For Tenant" API in :ref:`os-quota-sets`
    but that is per project quota.
    This issue is fixed in microversion 2.50, here onwards
    ``server_groups`` and ``server_group_members`` keys are
    returned in API response body.

Show the quota for Quota Class
==============================

.. rest_method:: GET /os-quota-class-sets/{id}

Show the quota for the Quota Class.

Normal response codes: 200

Error response codes: unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - id: quota_class_id

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_class_set: quota_class_set
  - cores: cores_quota_class
  - id: quota_class_id_body
  - instances: instances_quota_class
  - key_pairs: key_pairs_quota_class
  - metadata_items: metadata_items
  - ram: ram_quota_class
  - fixed_ips: fixed_ips_quota_class
  - floating_ips: floating_ips_quota_class
  - networks: networks_quota_optional
  - security_group_rules: security_group_rules_quota_class
  - security_groups: security_groups_quota_class
  - server_groups: server_groups_quota_class
  - server_group_members: server_group_members_quota_class
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files_quota_class

**Example Show A Quota Class: JSON response(2.50)**

.. literalinclude:: ../../doc/api_samples/os-quota-class-sets/v2.50/quota-classes-show-get-resp.json
   :language: javascript

Create or Update Quotas for Quota Class
=======================================

.. rest_method:: PUT /os-quota-class-sets/{id}

Update the quotas for the Quota Class.

If the requested Quota Class is not found in the DB, then the API will create the one.
Only 'default' quota class is valid and used to set the default quotas, all other quota class
would not be used anywhere.

Normal response codes: 200

Error response codes: badRequest(400), unauthorized(401), forbidden(403)

Request
-------

.. rest_parameters:: parameters.yaml

  - id: quota_class_id
  - quota_class_set: quota_class_set
  - cores: cores_quota_class_optional
  - instances: instances_quota_class_optional
  - key_pairs: key_pairs_quota_class_optional
  - metadata_items: metadata_items_quota_optional
  - ram: ram_quota_class_optional
  - server_groups: server_groups_quota_class_optional
  - server_group_members: server_group_members_quota_optional
  - fixed_ips: fixed_ips_quota_class_optional
  - floating_ips: floating_ips_quota_class_optional
  - networks: networks_quota_optional
  - security_group_rules: security_group_rules_quota_class_optional
  - security_groups: security_groups_quota_class_optional
  - injected_file_content_bytes: injected_file_content_bytes_quota_optional
  - injected_file_path_bytes: injected_file_path_bytes_quota_optional
  - injected_files: injected_files_quota_class_optional

**Example Update Quotas: JSON request(2.50)**

.. literalinclude:: ../../doc/api_samples/os-quota-class-sets/v2.50/quota-classes-update-post-req.json
   :language: javascript

Response
--------

.. rest_parameters:: parameters.yaml

  - quota_class_set: quota_class_set
  - cores: cores_quota_class
  - instances: instances_quota_class
  - key_pairs: key_pairs_quota_class
  - metadata_items: metadata_items
  - ram: ram_quota_class
  - fixed_ips: fixed_ips_quota_class
  - floating_ips: floating_ips_quota_class
  - networks: networks_quota_optional
  - security_group_rules: security_group_rules_quota_class
  - security_groups: security_groups_quota_class
  - server_groups: server_groups_quota_class
  - server_group_members: server_group_members_quota_class
  - injected_file_content_bytes: injected_file_content_bytes
  - injected_file_path_bytes: injected_file_path_bytes
  - injected_files: injected_files_quota_class

**Example Update Quotas: JSON response(2.50)**

.. literalinclude:: ../../doc/api_samples/os-quota-class-sets/v2.50/quota-classes-update-post-resp.json
   :language: javascript
