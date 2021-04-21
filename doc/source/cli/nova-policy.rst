===========
nova-policy
===========

.. program:: nova-policy

Synopsis
========

::

  nova-policy [<options>...]

Description
===========

:program:`nova-policy` is a tool that allows for inspection of policy file
configuration. It provides a way to identify the actions available for a user.
It does not require a running deployment: validation runs against the policy
files typically located at ``/etc/nova/policy.yaml`` and in the
``/etc/nova/policy.d`` directory. These paths are configurable via the
``[oslo_config] policy_file`` and ``[oslo_config] policy_dirs`` configuration
options, respectively.

Options
=======

.. rubric:: General options

.. include:: opts/common.rst

.. rubric:: User options

.. option:: --os-roles <auth-roles>

    Defaults to ``$OS_ROLES``.

.. option:: --os-tenant-id <auth-tenant-id>

    Defaults to ``$OS_TENANT_ID``.

.. option:: --os-user-id <auth-user-id>

    Defaults to ``$OS_USER_ID``.

.. rubric:: Debugger options

.. include:: opts/debugger.rst

Commands
========

policy check
------------

::

    nova-policy policy check [-h] [--api-name <name>]
                             [--target <target> [<target>...]

Prints all passing policy rules for the given user.

.. rubric:: Options

.. option:: --api-name <name>

    Return only the passing policy rules containing the given API name.
    If unspecified, all passing policy rules will be returned.

.. option:: --target <target> [<target>...]

    The target(s) against which the policy rule authorization will be tested.
    The available targets are: ``project_id``, ``user_id``, ``quota_class``,
    ``availability_zone``, ``instance_id``.
    When ``instance_id`` is used, the other targets will be overwritten.
    If unspecified, the given user will be considered as the target.

Files
=====

* ``/etc/nova/nova.conf``
* ``/etc/nova/policy.yaml``
* ``/etc/nova/policy.d/``

See Also
========

:doc:`nova-manage(1) <nova-manage>`,
:doc:`nova-status(1) <nova-status>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`__
