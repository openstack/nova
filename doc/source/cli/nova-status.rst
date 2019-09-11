===========
nova-status
===========

--------------------------------------
CLI interface for nova status commands
--------------------------------------

:Author: openstack@lists.openstack.org
:Copyright: OpenStack Foundation
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

::

  nova-status <category> <action> [<args>]

Description
===========

:program:`nova-status` is a tool that provides routines for checking the status
of a Nova deployment.

Options
=======

The standard pattern for executing a :program:`nova-status` command is::

    nova-status <category> <command> [<args>]

Run without arguments to see a list of available command categories::

    nova-status

Categories are:

* ``upgrade``

Detailed descriptions are below.

You can also run with a category argument such as ``upgrade`` to see a list of
all commands in that category::

    nova-status upgrade

These sections describe the available categories and arguments for
:program:`nova-status`.

Upgrade
~~~~~~~

.. _nova-status-checks:

``nova-status upgrade check``
  Performs a release-specific readiness check before restarting services with
  new code. This command expects to have complete configuration and access
  to databases and services within a cell. For example, this check may query
  the Nova API database and one or more cell databases. It may also make
  requests to other services such as the Placement REST API via the Keystone
  service catalog.

  **Return Codes**

  .. list-table::
     :widths: 20 80
     :header-rows: 1

     * - Return code
       - Description
     * - 0
       - All upgrade readiness checks passed successfully and there is nothing
         to do.
     * - 1
       - At least one check encountered an issue and requires further
         investigation. This is considered a warning but the upgrade may be OK.
     * - 2
       - There was an upgrade status check failure that needs to be
         investigated. This should be considered something that stops an
         upgrade.
     * - 255
       - An unexpected error occurred.

  **History of Checks**

  **15.0.0 (Ocata)**

  * Checks are added for cells v2 so ``nova-status upgrade check`` should be
    run *after* running the ``nova-manage cell_v2 simple_cell_setup``
    command.
  * Checks are added for the Placement API such that there is an endpoint in
    the Keystone service catalog, the service is running and the check can
    make a successful request to the endpoint. The command also checks to
    see that there are compute node resource providers checking in with the
    Placement service. More information on the Placement service can be found
    at :placement-doc:`Placement API <>`.

  **16.0.0 (Pike)**

  * Checks for the Placement API are modified to require version 1.4, that
    is needed in Pike and further for nova-scheduler to work correctly.

  **17.0.0 (Queens)**

  * Checks for the Placement API are modified to require version 1.17.

  **18.0.0 (Rocky)**

  * Checks for the Placement API are modified to require version 1.28.
  * Checks that ironic instances have had their embedded flavors migrated to
    use custom resource classes.
  * Checks for ``nova-osapi_compute`` service versions that are less than 15
    across all cell mappings which might cause issues when querying instances
    depending on how the **nova-api** service is configured.
    See https://bugs.launchpad.net/nova/+bug/1759316 for details.
  * Checks that existing instances have been migrated to have a matching
    request spec in the API DB.

  **19.0.0 (Stein)**

  * Checks for the Placement API are modified to require version 1.30.
  * Checks are added for the **nova-consoleauth** service to warn and provide
    additional instructions to set **[workarounds]enable_consoleauth = True**
    while performing a live/rolling upgrade.
  * The "Resource Providers" upgrade check was removed since the placement
    service code is being extracted from nova and the related tables are no
    longer used in the ``nova_api`` database.
  * The "API Service Version" upgrade check was removed since the corresponding
    code for that check was removed in Stein.

  **20.0.0 (Train)**

  * Checks for the Placement API are modified to require version 1.32.
  * Checks to ensure block-storage (cinder) API version 3.44 is
    available in order to support multi-attach volumes.
    If ``[cinder]/auth_type`` is not configured this is a no-op check.
  * The "**nova-consoleauth** service" upgrade check was removed since the
    service was removed in Train.
  * The ``Request Spec Migration`` check was removed.

See Also
========

* :nova-doc:`OpenStack Nova <>`

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`_
