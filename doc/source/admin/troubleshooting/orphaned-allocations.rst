Orphaned resource allocations
=============================

Problem
-------

There are orphaned resource allocations in the placement service which can
cause resource providers to:

* Appear to the scheduler to be more utilized than they really are
* Prevent deletion of compute services

One scenario in which this could happen is a compute service host is having
problems so the administrator forces it down and evacuates servers from it.
Note that in this case "evacuates" refers to the server ``evacuate`` action,
not live migrating all servers from the running compute service. Assume the
compute host is down and fenced.

In this case, the servers have allocations tracked in placement against both
the down source compute node and their current destination compute host. For
example, here is a server *vm1* which has been evacuated from node *devstack1*
to node *devstack2*:

.. code-block:: console

  $ openstack --os-compute-api-version 2.53 compute service list --service nova-compute
  +--------------------------------------+--------------+-----------+------+---------+-------+----------------------------+
  | ID                                   | Binary       | Host      | Zone | Status  | State | Updated At                 |
  +--------------------------------------+--------------+-----------+------+---------+-------+----------------------------+
  | e3c18c2d-9488-4863-b728-f3f292ec5da8 | nova-compute | devstack1 | nova | enabled | down  | 2019-10-25T20:13:51.000000 |
  | 50a20add-cc49-46bd-af96-9bb4e9247398 | nova-compute | devstack2 | nova | enabled | up    | 2019-10-25T20:13:52.000000 |
  | b92afb2e-cd00-4074-803e-fff9aa379c2f | nova-compute | devstack3 | nova | enabled | up    | 2019-10-25T20:13:53.000000 |
  +--------------------------------------+--------------+-----------+------+---------+-------+----------------------------+
  $ vm1=$(openstack server show vm1 -f value -c id)
  $ openstack server show $vm1 -f value -c OS-EXT-SRV-ATTR:host
  devstack2

The server now has allocations against both *devstack1* and *devstack2*
resource providers in the placement service:

.. code-block:: console

  $ devstack1=$(openstack resource provider list --name devstack1 -f value -c uuid)
  $ devstack2=$(openstack resource provider list --name devstack2 -f value -c uuid)
  $ openstack resource provider show --allocations $devstack1
  +-------------+-----------------------------------------------------------------------------------------------------------+
  | Field       | Value                                                                                                     |
  +-------------+-----------------------------------------------------------------------------------------------------------+
  | uuid        | 9546fce4-9fb5-4b35-b277-72ff125ad787                                                                      |
  | name        | devstack1                                                                                                 |
  | generation  | 6                                                                                                         |
  | allocations | {u'a1e6e0b2-9028-4166-b79b-c177ff70fbb7': {u'resources': {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1}}} |
  +-------------+-----------------------------------------------------------------------------------------------------------+
  $ openstack resource provider show --allocations $devstack2
  +-------------+-----------------------------------------------------------------------------------------------------------+
  | Field       | Value                                                                                                     |
  +-------------+-----------------------------------------------------------------------------------------------------------+
  | uuid        | 52d0182d-d466-4210-8f0d-29466bb54feb                                                                      |
  | name        | devstack2                                                                                                 |
  | generation  | 3                                                                                                         |
  | allocations | {u'a1e6e0b2-9028-4166-b79b-c177ff70fbb7': {u'resources': {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1}}} |
  +-------------+-----------------------------------------------------------------------------------------------------------+
  $ openstack --os-placement-api-version 1.12 resource provider allocation show $vm1
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | resource_provider                    | generation | resources                                      | project_id                       | user_id                          |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | 9546fce4-9fb5-4b35-b277-72ff125ad787 |          6 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} | 2f3bffc5db2b47deb40808a4ed2d7c7a | 2206168427c54d92ae2b2572bb0da9af |
  | 52d0182d-d466-4210-8f0d-29466bb54feb |          3 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} | 2f3bffc5db2b47deb40808a4ed2d7c7a | 2206168427c54d92ae2b2572bb0da9af |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+

One way to find all servers that were evacuated from *devstack1* is:

.. code-block:: console

  $ nova migration-list --source-compute devstack1 --migration-type evacuation
  +----+--------------------------------------+-------------+-----------+----------------+--------------+-------------+--------+--------------------------------------+------------+------------+----------------------------+----------------------------+------------+
  | Id | UUID                                 | Source Node | Dest Node | Source Compute | Dest Compute | Dest Host   | Status | Instance UUID                        | Old Flavor | New Flavor | Created At                 | Updated At                 | Type       |
  +----+--------------------------------------+-------------+-----------+----------------+--------------+-------------+--------+--------------------------------------+------------+------------+----------------------------+----------------------------+------------+
  | 1  | 8a823ba3-e2e9-4f17-bac5-88ceea496b99 | devstack1   | devstack2 | devstack1      | devstack2    | 192.168.0.1 | done   | a1e6e0b2-9028-4166-b79b-c177ff70fbb7 | None       | None       | 2019-10-25T17:46:35.000000 | 2019-10-25T17:46:37.000000 | evacuation |
  +----+--------------------------------------+-------------+-----------+----------------+--------------+-------------+--------+--------------------------------------+------------+------------+----------------------------+----------------------------+------------+

Trying to delete the resource provider for *devstack1* will fail while there
are allocations against it:

.. code-block:: console

  $ openstack resource provider delete $devstack1
  Unable to delete resource provider 9546fce4-9fb5-4b35-b277-72ff125ad787: Resource provider has allocations. (HTTP 409)

Solution
--------

Using the example resources above, remove the allocation for server *vm1* from
the *devstack1* resource provider. If you have `osc-placement
<https://pypi.org/project/osc-placement/>`_ 1.8.0 or newer, you can use the
:command:`openstack resource provider allocation unset` command to remove the
allocations for consumer *vm1* from resource provider *devstack1*:

.. code-block:: console

  $ openstack --os-placement-api-version 1.12 resource provider allocation \
      unset --provider $devstack1 $vm1
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | resource_provider                    | generation | resources                                      | project_id                       | user_id                          |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | 52d0182d-d466-4210-8f0d-29466bb54feb |          4 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} | 2f3bffc5db2b47deb40808a4ed2d7c7a | 2206168427c54d92ae2b2572bb0da9af |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+

If you have *osc-placement* 1.7.x or older, the ``unset`` command is not
available and you must instead overwrite the allocations. Note that we do not
use :command:`openstack resource provider allocation delete` here because that
will remove the allocations for the server from all resource providers,
including *devstack2* where it is now running; instead, we use
:command:`openstack resource provider allocation set` to overwrite the
allocations and only retain the *devstack2* provider allocations. If you do
remove all allocations for a given server, you can heal them later. See `Using
heal_allocations`_ for details.

.. code-block:: console

  $ openstack --os-placement-api-version 1.12 resource provider allocation set $vm1 \
      --project-id 2f3bffc5db2b47deb40808a4ed2d7c7a \
      --user-id 2206168427c54d92ae2b2572bb0da9af \
      --allocation rp=52d0182d-d466-4210-8f0d-29466bb54feb,VCPU=1 \
      --allocation rp=52d0182d-d466-4210-8f0d-29466bb54feb,MEMORY_MB=512 \
      --allocation rp=52d0182d-d466-4210-8f0d-29466bb54feb,DISK_GB=1
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | resource_provider                    | generation | resources                                      | project_id                       | user_id                          |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+
  | 52d0182d-d466-4210-8f0d-29466bb54feb |          4 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} | 2f3bffc5db2b47deb40808a4ed2d7c7a | 2206168427c54d92ae2b2572bb0da9af |
  +--------------------------------------+------------+------------------------------------------------+----------------------------------+----------------------------------+

Once the *devstack1* resource provider allocations have been removed using
either of the approaches above, the *devstack1* resource provider can be
deleted:

.. code-block:: console

  $ openstack resource provider delete $devstack1

And the related compute service if desired:

.. code-block:: console

  $ openstack --os-compute-api-version 2.53 compute service delete e3c18c2d-9488-4863-b728-f3f292ec5da8

For more details on the resource provider commands used in this guide, refer
to the `osc-placement plugin documentation`_.

.. _osc-placement plugin documentation: https://docs.openstack.org/osc-placement/latest/

Using heal_allocations
~~~~~~~~~~~~~~~~~~~~~~

If you have a particularly troubling allocation consumer and just want to
delete its allocations from all providers, you can use the
:command:`openstack resource provider allocation delete` command and then
heal the allocations for the consumer using the
:ref:`heal_allocations command <heal_allocations_cli>`. For example:

.. code-block:: console

  $ openstack resource provider allocation delete $vm1
  $ nova-manage placement heal_allocations --verbose --instance $vm1
  Looking for instances in cell: 04879596-d893-401c-b2a6-3d3aa096089d(cell1)
  Found 1 candidate instances.
  Successfully created allocations for instance a1e6e0b2-9028-4166-b79b-c177ff70fbb7.
  Processed 1 instances.
  $ openstack resource provider allocation show $vm1
  +--------------------------------------+------------+------------------------------------------------+
  | resource_provider                    | generation | resources                                      |
  +--------------------------------------+------------+------------------------------------------------+
  | 52d0182d-d466-4210-8f0d-29466bb54feb |          5 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} |
  +--------------------------------------+------------+------------------------------------------------+

Note that deleting allocations and then relying on ``heal_allocations`` may not
always be the best solution since healing allocations does not account for some
things:

* `Migration-based allocations`_ would be lost if manually deleted during a
  resize. These are allocations tracked by the migration resource record
  on the source compute service during a migration.
* Healing allocations does not supported nested resource allocations before the
  20.0.0 (Train) release.

If you do use the ``heal_allocations`` command to cleanup allocations for a
specific trouble instance, it is recommended to take note of what the
allocations were before you remove them in case you need to reset them manually
later. Use the :command:`openstack resource provider allocation show` command
to get allocations for a consumer before deleting them, e.g.:

.. code-block:: console

  $ openstack --os-placement-api-version 1.12 resource provider allocation show $vm1

.. _Migration-based allocations: https://specs.openstack.org/openstack/nova-specs/specs/queens/implemented/migration-allocations.html
