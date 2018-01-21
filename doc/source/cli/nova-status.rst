===========
nova-status
===========

--------------------------------------
CLI interface for nova status commands
--------------------------------------

:Author: openstack@lists.openstack.org
:Date:   2016-12-16
:Copyright: OpenStack Foundation
:Version: 15.0.0
:Manual section: 1
:Manual group: cloud computing

Synopsis
========

  nova-status <category> <action> [<args>]

Description
===========

`nova-status` is a tool that provides routines for checking the status of a
Nova deployment.

Options
=======

The standard pattern for executing a `nova-status` command is::

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
`nova-status`.

Upgrade
~~~~~~~

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
    at: `<https://docs.openstack.org/nova/latest/user/placement.html>`_

  **16.0.0 (Pike)**

  * Checks for the Placement API are modified to require version 1.4, that
    is needed in Pike and further for nova-scheduler to work correctly.

  **17.0.0 (Queens)**

  * Checks for the Placement API are modified to require version 1.17.

See Also
========

* OpenStack Nova Docs: `<https://docs.openstack.org/nova/latest/>`_

Bugs
====

* Nova bugs are managed at `Launchpad <https://bugs.launchpad.net/nova>`_
