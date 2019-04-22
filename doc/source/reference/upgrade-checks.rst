==============
Upgrade checks
==============

Nova provides automated :ref:`upgrade check tooling <nova-status-checks>` to
assist deployment tools in verifying critical parts of the deployment,
especially when it comes to major changes during upgrades that require operator
intervention.

This guide covers the background on nova's upgrade check tooling, how it is
used, and what to look for in writing new checks.

Background
==========

Nova has historically supported offline database schema migrations
(``nova-manage db sync``) and :ref:`online data migrations <data-migrations>`
during upgrades.

The ``nova-status upgrade check`` command was introduced in the 15.0.0 Ocata
release to aid in the verification of two major required changes in that
release, namely Placement and Cells v2.

Integration with the Placement service and deploying Cells v2 was optional
starting in the 14.0.0 Newton release and made required in the Ocata release.
The nova team working on these changes knew that there were required deployment
changes to successfully upgrade to Ocata. In addition, the required deployment
changes were not things that could simply be verified in a database migration
script, e.g. a migration script should not make REST API calls to Placement.

So ``nova-status upgrade check`` was written to provide an automated
"pre-flight" check to verify that required deployment steps were performed
prior to upgrading to Ocata.

Reference the `Ocata changes`_ for implementation details.

.. _Ocata changes: https://review.opendev.org/#/q/topic:bp/resource-providers-scheduler-db-filters+status:merged+file:%255Enova/cmd/status.py

Guidelines
==========

* The checks should be able to run within a virtual environment or container.
  All that is required is a full configuration file, similar to running other
  ``nova-manage`` type administration commands. In the case of nova, this
  means having :oslo.config:group:`api_database`,
  :oslo.config:group:`placement`, etc sections configured.

* Candidates for automated upgrade checks are things in a project's upgrade
  release notes which can be verified via the database. For example, when
  upgrading to Cells v2 in Ocata, one required step was creating
  "cell mappings" for ``cell0`` and ``cell1``. This can easily be verified by
  checking the contents of the ``cell_mappings`` table in the ``nova_api``
  database.

* Checks will query the database(s) and potentially REST APIs (depending on the
  check) but should not expect to run RPC calls. For example, a check should
  not require that the ``nova-compute`` service is running on a particular
  host.

* Checks are typically meant to be run before re-starting and upgrading to new
  service code, which is how `grenade uses them`_, but they can also be run
  as a :ref:`post-install verify step <verify-install-nova-status>` which is
  how `openstack-ansible`_ also uses them. The high-level set of upgrade steps
  for upgrading nova in grenade is:

  * Install new code
  * Sync the database schema for new models
    (``nova-manage api_db sync``; ``nova-manage db sync``)
  * Run the online data migrations (``nova-manage db online_data_migrations``)
  * Run the upgrade check (``nova-status upgrade check``)
  * Restart services with new code

* Checks must be idempotent so they can be run repeatedly and the results are
  always based on the latest data. This allows an operator to run the checks,
  fix any issues reported, and then iterate until the status check no longer
  reports any issues.

* Checks which cannot easily, or should not, be run within offline database
  migrations are a good candidate for these CLI-driven checks. For example,
  ``instances`` records are in the cell database and for each instance there
  should be a corresponding ``request_specs`` table entry in the ``nova_api``
  database. A ``nova-manage db online_data_migrations`` routine was added in
  the Newton release to back-fill request specs for existing instances, and
  `in Rocky`_ an upgrade check was added to make sure all non-deleted instances
  have a request spec so compatibility code can be removed in Stein. In older
  releases of nova we would have added a `blocker migration`_ as part of the
  database schema migrations to make sure the online data migrations had been
  completed before the upgrade could proceed.

  .. note:: Usage of ``nova-status upgrade check`` does not preclude the need
            for blocker migrations within a given database, but in the case of
            request specs the check spans multiple databases and was a better
            fit for the nova-status tooling.

* All checks should have an accompanying upgrade release note.

.. _grenade uses them: https://github.com/openstack-dev/grenade/blob/dc7f4a4ba/projects/60_nova/upgrade.sh#L96
.. _openstack-ansible: https://review.opendev.org/#/c/575125/
.. _in Rocky: https://review.opendev.org/#/c/581813/
.. _blocker migration: https://review.opendev.org/#/c/289450/

Structure
=========

There is no graph logic for checks, meaning each check is meant to be run
independently of other checks in the same set. For example, a project could
have five checks which run serially but that does not mean the second check
in the set depends on the results of the first check in the set, or the
third check depends on the second, and so on.

The base framework is fairly simple as can be seen from the `initial change`_.
Each check is registered in the ``_upgrade_checks`` variable and the ``check``
method executes each check and records the result. The most severe result is
recorded for the final return code.

There are one of three possible results per check:

* ``Success``: All upgrade readiness checks passed successfully and there is
  nothing to do.
* ``Warning``: At least one check encountered an issue and requires further
  investigation. This is considered a warning but the upgrade may be OK.
* ``Failure``: There was an upgrade status check failure that needs to be
  investigated. This should be considered something that stops an upgrade.

The ``UpgradeCheckResult`` object provides for adding details when there
is a warning or failure result which generally should refer to how to resolve
the failure, e.g. maybe ``nova-manage db online_data_migrations`` is
incomplete and needs to be run again.

Using the `cells v2 check`_ as an example, there are really two checks
involved:

1. Do the cell0 and cell1 mappings exist?
2. Do host mappings exist in the API database if there are compute node
   records in the cell database?

Failing either check results in a ``Failure`` status for that check and return
code of ``2`` for the overall run.

The initial `placement check`_ provides an example of a warning response. In
that check, if there are fewer resource providers in Placement than there are
compute nodes in the cell database(s), the deployment may be underutilized
because the ``nova-scheduler`` is using the Placement service to determine
candidate hosts for scheduling.

Warning results are good for cases where scenarios are known to run through
a rolling upgrade process, e.g. ``nova-compute`` being configured to report
resource provider information into the Placement service. These are things
that should be investigated and completed at some point, but might not cause
any immediate failures.

The results feed into a standard output for the checks:

.. code-block:: console

  $ nova-status upgrade check
  +----------------------------------------------------+
  | Upgrade Check Results                              |
  +----------------------------------------------------+
  | Check: Cells v2                                    |
  | Result: Success                                    |
  | Details: None                                      |
  +----------------------------------------------------+
  | Check: Placement API                               |
  | Result: Failure                                    |
  | Details: There is no placement-api endpoint in the |
  |          service catalog.                          |
  +----------------------------------------------------+

.. note:: Long-term the framework for upgrade checks will come from the
          `oslo.upgradecheck library`_.

.. _initial change: https://review.opendev.org/#/c/411517/
.. _cells v2 check: https://review.opendev.org/#/c/411525/
.. _placement check: https://review.opendev.org/#/c/413250/
.. _oslo.upgradecheck library: http://opendev.org/openstack/oslo.upgradecheck/

Other
=====

Documentation
-------------

Each check should be documented in the
:ref:`history section <nova-status-checks>` of the CLI guide and have a
release note. This is important since the checks can be run in an isolated
environment apart from the actual deployed version of the code and since the
checks should be idempotent, the history / change log is good for knowing
what is being validated.

Backports
---------

Sometimes upgrade checks can be backported to aid in pre-empting bugs on
stable branches. For example, a check was added for `bug 1759316`_ in Rocky
which was also backported to stable/queens in case anyone upgrading from Pike
to Queens would hit the same issue. Backportable checks are generally only
made for latent bugs since someone who has already passed checks and upgraded
to a given stable branch should not start failing after a patch release on that
same branch. For this reason, any check being backported should have a release
note with it.

.. _bug 1759316: https://bugs.launchpad.net/nova/+bug/1759316

Other projects
--------------

A community-wide `goal for the Stein release`_ is adding the same type of
``$PROJECT-status upgrade check`` tooling to other projects to ease in
upgrading OpenStack across the board. So while the guidelines in this document
are primarily specific to nova, they should apply generically to other projects
wishing to incorporate the same tooling.

.. _goal for the Stein release: https://governance.openstack.org/tc/goals/stein/upgrade-checkers.html

FAQs
----

#. How is the nova-status upgrade script packaged and deployed?

   There is a ``console_scripts`` entry for ``nova-status`` in the
   ``setup.cfg`` file.

#. Why are there multiple parts to the command structure, i.e. "upgrade" and
   "check"?

   This is an artifact of how the ``nova-manage`` command is structured which
   has categories of sub-commands, like ``nova-manage db`` is a sub-category
   made up of other sub-commands like ``nova-manage db sync``. The
   ``nova-status upgrade check`` command was written in the same way for
   consistency and extensibility if other sub-commands need to be added later.

#. Where should the documentation live for projects other than nova?

   As part of the standard OpenStack project `documentation guidelines`_ the
   command should be documented under ``doc/source/cli`` in each project repo.

#. Why is the upgrade check command not part of the standard python-\*client
   CLIs?

   The ``nova-status`` command was modeled after the ``nova-manage`` command
   which is meant to be admin-only and has direct access to the database,
   unlike other CLI packages like python-novaclient which requires a token
   and communicates with nova over the REST API. Because of this, it is also
   possible to write commands in ``nova-manage`` and ``nova-status`` that can
   work while the API service is down for maintenance.

#. Can upgrade checks only be for N-1 to N version upgrades?

   No, not necessarily. The upgrade checks are also an essential part of
   `fast-forward upgrades`_ to make sure that as you roll through each release
   performing schema (data model) updates and data migrations that you are
   also completing all of the necessary changes. For example, if you are
   fast forward upgrading from Ocata to Rocky, something could have been
   added, deprecated or removed in Pike or Queens and a pre-upgrade check is
   a way to make sure the necessary steps were taking while upgrading through
   those releases before restarting the Rocky code at the end.

.. _documentation guidelines: https://docs.openstack.org/doc-contrib-guide/project-guides.html
.. _fast-forward upgrades: https://wiki.openstack.org/wiki/Fast_forward_upgrades
