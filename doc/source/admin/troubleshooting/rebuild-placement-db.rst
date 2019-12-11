Rebuild placement DB
====================

Problem
-------

You have somehow changed a nova cell database and the ``compute_nodes`` table
entries are now reporting different uuids to the placement service but
placement already has ``resource_providers`` table entries with the same
names as those computes so the resource providers in placement and the
compute nodes in the nova database are not synchronized. Maybe this happens
as a result of restoring the nova cell database from a backup where the compute
hosts have not changed but they are using different uuids.

Nova reports compute node inventory to placement using the
``hypervisor_hostname`` and uuid of the ``compute_nodes`` table to the
placement ``resource_providers`` table, which has a unique constraint on the
name (hostname in this case) and uuid. Trying to create a new resource provider
with a new uuid but the same name as an existing provider results in a 409
error from placement, such as in `bug 1817833`_.

.. _bug 1817833: https://bugs.launchpad.net/nova/+bug/1817833

Solution
--------

.. warning:: This is likely a last resort when *all* computes and resource
             providers are not synchronized and it is simpler to just rebuild
             the placement database from the current state of nova. This may,
             however, not work when using placement for more advanced features
             such as :neutron-doc:`ports with minimum bandwidth guarantees </admin/config-qos-min-bw>`
             or `accelerators <https://docs.openstack.org/cyborg/latest/>`_.
             Obviously testing first in a pre-production environment is ideal.

These are the steps at a high level:

#. Make a backup of the existing placement database in case these steps fail
   and you need to start over.

#. Recreate the placement database and run the schema migrations to
   initialize the placement database.

#. Either restart or wait for the
   :oslo.config:option:`update_resources_interval` on the ``nova-compute``
   services to report resource providers and their inventory to placement.

#. Run the :ref:`nova-manage placement heal_allocations <heal_allocations_cli>`
   command to report allocations to placement for the existing instances in
   nova.

#. Run the :ref:`nova-manage placement sync_aggregates <sync_aggregates_cli>`
   command to synchronize nova host aggregates to placement resource provider
   aggregates.

Once complete, test your deployment as usual, e.g. running Tempest integration
and/or Rally tests, creating, migrating and deleting a server, etc.
