Understanding Nova Policies
===========================

.. warning::

   JSON formatted policy file is deprecated since Nova 22.0.0(Victoria).
   Use YAML formatted file. Use `oslopolicy-convert-json-to-yaml`__ tool
   to convert the existing JSON to YAML formatted policy file in backward
   compatible way.

.. __: https://docs.openstack.org/oslo.policy/latest/cli/oslopolicy-convert-json-to-yaml.html

Nova supports a rich policy system that has evolved significantly over its
lifetime. Initially, this took the form of a large, mostly hand-written
``policy.yaml`` file but, starting in the Newton (14.0.0) release, policy
defaults have been defined in the codebase, requiring the ``policy.yaml``
file only to override these defaults.

In the Ussuri (21.0.0) release, further work was undertaken to address some
issues that had been identified:

#. No global vs project admin. The ``admin_only`` role is used for the global
   admin that is able to make almost any change to Nova, and see all details
   of the Nova system. The rule passes for any user with an admin role, it
   doesn’t matter which project is used.

#. No read-only roles. Since several APIs tend to share a single policy rule
   for read and write actions, they did not provide the granularity necessary
   for read-only access roles.

#. The ``admin_or_owner`` role did not work as expected. For most APIs with
   ``admin_or_owner``, the project authentication happened in a separate
   component than API in Nova that did not honor changes to policy. As a
   result, policy could not override hard-coded in-project checks.

Keystone comes with ``admin``, ``member`` and ``reader`` roles by default.
Please refer to :keystone-doc:`this document </admin/service-api-protection.html>`
for more information about these new defaults. In addition, keystone supports
a new "system scope" concept that makes it easier to protect deployment level
resources from project or system level resources. Please refer to
:keystone-doc:`this document </admin/tokens-overview.html#authorization-scopes>`
and `system scope specification <https://specs.openstack.org/openstack/keystone-specs/specs/keystone/queens/system-scope.html>`_ to understand the scope concept.

In the Nova 25.0.0 (Yoga) release, Nova policies implemented
the scope concept and default roles provided by keystone (admin, member,
and reader). Using common roles from keystone reduces the likelihood of
similar, but different, roles implemented across projects or deployments
(e.g., a role called ``observer`` versus ``reader`` versus ``auditor``).
With the help of the new defaults it is easier to understand who can do
what across projects, reduces divergence, and increases interoperability.

The below sections explain how these new defaults in the Nova can solve the
first two issues mentioned above and extend more functionality to end users
in a safe and secure way.

More information is provided in the `nova specification <https://specs.openstack.org/openstack/nova-specs/specs/ussuri/approved/policy-defaults-refresh.html>`_.

Scope
-----

OpenStack Keystone supports different scopes in tokens.
These are described :keystone-doc:`here </admin/tokens-overview.html#authorization-scopes>`.
Token scopes represent the layer of authorization. Policy ``scope_types``
represent the layer of authorization required to access an API.

.. note::

     The ``scope_type`` of each policy is hardcoded  to ``project`` scoped
     and is not overridable via the policy file.

Nova policies have implemented the scope concept by defining the ``scope_type``
for all the policies to ``project`` scoped. It means if user tries to access
nova APIs with ``system`` scoped token they will get 403 permission denied
error.

For example, consider the ``POST /os-server-groups`` API.

.. code::

    # Create a new server group
    # POST  /os-server-groups
    # Intended scope(s): project
    #"os_compute_api:os-server-groups:create": "rule:project_member_api"

Policy scope is disabled by default to allow operators to migrate from
the old policy enforcement system in a graceful way. This can be
enabled by configuring the :oslo.config:option:`oslo_policy.enforce_scope`
option to ``True``.

.. note::

  [oslo_policy]
  enforce_scope=True


Roles
-----

You can refer to :keystone-doc:`this </admin/service-api-protection.html>`
document to know about all available defaults from Keystone.

Along with the ``scope_type`` feature, Nova policy defines new
defaults for each policy.

.. rubric:: ``reader``

This provides read-only access to the resources. Nova policies are defaulted
to below rules:

.. code-block:: python

    policy.RuleDefault(
        name="project_reader",
        check_str="role:reader and project_id:%(project_id)s",
        description="Default rule for Project level read only APIs."
    )

Using it in policy rule (with admin + reader access): (because we want to keep legacy admin behavior the same we need to give access of reader APIs to admin role too.)

.. code-block:: python

    policy.DocumentedRuleDefault(
        name='os_compute_api:servers:show',
        check_str='role:admin or (' + 'role:reader and project_id:%(project_id)s)',
        description="Show a server",
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            }
        ],
        scope_types=['project'],
    )

OR

.. code-block:: python

    policy.RuleDefault(
        name="admin_api",
        check_str="role:admin",
        description="Default rule for administrative APIs."
    )

    policy.DocumentedRuleDefault(
        name='os_compute_api:servers:show',
        check_str='rule: admin or rule:project_reader',
        description='Show a server',
        operations=[
            {
                'method': 'GET',
                'path': '/servers/{server_id}'
            }
        ],
        scope_types=['project'],
    )

.. rubric:: ``member``

project-member is denoted by someone with the member role on a project. It is
intended to be used by end users who consume resources within a project
which requires higher permission than reader role but less than admin role.
It inherits all the permissions of a project-reader.

project-member persona in the policy check string:

.. code-block:: python

    policy.RuleDefault(
        name="project_member",
        check_str="role:member and project_id:%(project_id)s",
        description="Default rule for Project level non admin APIs."
    )

Using it in policy rule (with admin + member access): (because we want to keep legacy admin behavior, admin role gets access to the project level member APIs.)

.. code-block:: python

    policy.DocumentedRuleDefault(
        name='os_compute_api:servers:create',
        check_str='role:admin or (' + 'role:member and project_id:%(project_id)s)',
        description='Create a server',
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project'],
    )

OR

.. code-block:: python

    policy.RuleDefault(
        name="admin_api",
        check_str="role:admin",
        description="Default rule for administrative APIs."
    )

    policy.DocumentedRuleDefault(
        name='os_compute_api:servers:create',
        check_str='rule_admin or rule:project_member',
        description='Create a server',
        operations=[
            {
                'method': 'POST',
                'path': '/servers'
            }
        ],
        scope_types=['project'],
    )

'project_id:%(project_id)s' in the check_str is important to restrict the
access within the requested project.

.. rubric:: ``admin``

This role is to perform the admin level write operations. Nova policies are
defaulted to below rules:

.. code-block:: python

   policy.DocumentedRuleDefault(
       name='os_compute_api:os-hypervisors:list',
       check_str='role:admin',
       scope_types=['project']
   )

With these new defaults, you can solve the problem of:

#. Providing the read-only access to the user. Polices are made more granular
   and defaulted to reader rules. For example: If you need to let someone audit
   your deployment for security purposes.

#. Customize the policy in better way. For example, you will be able
   to provide access to project level user to perform operations within
   their project only.

Nova supported scope & Roles
-----------------------------

Nova supports the below combination of scopes and roles where roles can be
overridden in the policy.yaml file but scope is not override-able.

#. ADMIN: ``admin`` role on ``project`` scope. This is an administrator to
   perform the admin level operations. Example: enable/disable compute
   service, Live migrate server etc.

#. PROJECT_MEMBER: ``member`` role on ``project`` scope. This is used to perform
   resource owner level operation within project. For example: Pause a server.

#. PROJECT_READER: ``reader`` role on ``project`` scope. This is used to perform
   read-only operation within project. For example: Get server.

#. PROJECT_MEMBER_OR_ADMIN: ``admin`` or ``member`` role on ``project`` scope.    Such policy rules are default to most of the owner level APIs and aling
   with `member` role legacy admin can continue to access those APIs.

#. PROJECT_READER_OR_ADMIN: ``admin`` or ``reader`` role on ``project`` scope.    Such policy rules are default to most of the read only APIs so that legacy
   admin can continue to access those APIs.

Backward Compatibility
----------------------

Backward compatibility with versions prior to 21.0.0 (Ussuri) is maintained by
supporting the old defaults and disabling the ``scope_type`` feature by default.
This means the old defaults and deployments that use them will keep working
as-is. However, we encourage every deployment to switch to the new policy. The
new defaults will be enabled by default in OpenStack 2023.1 (Nova 27.0.0)
release and old defaults will be removed starting in the OpenStack 2023.2
(Nova 28.0.0) release.

To implement the new default reader roles, some policies needed to become
granular. They have been renamed, with the old names still supported for
backwards compatibility.

Migration Plan
--------------

To have a graceful migration, Nova provides two flags to switch to the new
policy completely. You do not need to overwrite the policy file to adopt the
new policy defaults.

Here is step wise guide for migration:

#. Create scoped token:

   You need to create the new token with scope knowledge via below CLI:

   - :keystone-doc:`Create Project Scoped Token </admin/tokens-overview.html#operation_create_project_scoped_token>`.

#. Create new default roles in keystone if not done:

   If you do not have new defaults in Keystone then you can create and re-run
   the :keystone-doc:`Keystone Bootstrap </admin/bootstrap.html>`. Keystone
   added this support in 14.0.0 (Rocky) release.

#. Enable Scope Checks

   The :oslo.config:option:`oslo_policy.enforce_scope` flag is to enable the
   ``scope_type`` features. The scope of the token used in the request is
   always compared to the ``scope_type`` of the policy. If the scopes do not
   match, one of two things can happen. If :oslo.config:option:`oslo_policy.enforce_scope`
   is True, the request will be rejected. If  :oslo.config:option:`oslo_policy.enforce_scope`
   is False, an warning will be logged, but the request will be accepted
   (assuming the rest of the policy passes). The default value of this flag
   is False.

#. Enable new defaults

   The :oslo.config:option:`oslo_policy.enforce_new_defaults` flag switches
   the policy to new defaults-only. This flag controls whether or not to use
   old deprecated defaults when evaluating policies. If True, the old
   deprecated defaults are not evaluated. This means if any existing
   token is allowed for old defaults but is disallowed for new defaults,
   it will be rejected. The default value of this flag is False.

   .. note:: Before you enable this flag, you need to educate users about the
             different roles they need to use to continue using Nova APIs.

#. Check for deprecated policies

   A few policies were made more granular to implement the reader roles. New
   policy names are available to use. If old policy names which are renamed
   are overwritten in policy file, then warning will be logged. Please migrate
   those policies to new policy names.

NOTE::

  We recommend to enable the both scope as well new defaults together
  otherwise you may experience some late failures with unclear error
  messages. For example, if you enable new defaults and disable scope
  check then it will allow system users to access the APIs but fail
  later due to the project check which can be difficult to debug.

Below table show how legacy rules are mapped to new rules:

+--------------------+---------------------------+----------------+-----------+
| Legacy Rule        |    New Rules              |Operation       |scope_type |
+====================+===========================+================+===========+
| RULE_ADMIN_API     |-> ADMIN                   |Global resource | [project] |
|                    |                           |Write & Read    |           |
+--------------------+---------------------------+----------------+-----------+
|                    |-> ADMIN                   |Project admin   | [project] |
|                    |                           |level operation |           |
|                    +---------------------------+----------------+-----------+
| RULE_ADMIN_OR_OWNER|-> PROJECT_MEMBER_OR_ADMIN |Project resource| [project] |
|                    |                           |Write           |           |
|                    +---------------------------+----------------+-----------+
|                    |-> PROJECT_READER_OR_ADMIN |Project resource| [project] |
|                    |                           |Read            |           |
+--------------------+---------------------------+----------------+-----------+

We expect all deployments to migrate to the new policy by OpenStack 2023.1
(Nova 27.0.0) release so that we can remove the support of old policies.
