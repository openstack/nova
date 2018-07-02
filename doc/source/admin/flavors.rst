==============
Manage Flavors
==============

Admin users can use the :command:`openstack flavor` command to customize and
manage flavors. To see information for this command, run:

.. code-block:: console

    $ openstack flavor --help
    Command "flavor" matches:
      flavor create
      flavor delete
      flavor list
      flavor set
      flavor show
      flavor unset

.. note::

   Configuration rights can be delegated to additional users by redefining
   the access controls for ``os_compute_api:os-flavor-manage`` in
   ``/etc/nova/policy.json`` on the ``nova-api`` server.

.. note::

    Flavor customization can be limited by the hypervisor in use. For example
    the libvirt driver enables quotas on CPUs available to a VM, disk tuning,
    bandwidth I/O, watchdog behavior, random number generator device control,
    and instance VIF traffic control.

For information on the flavors and flavor extra specs, refer to
:doc:`/user/flavors`.

Create a flavor
---------------

#. List flavors to show the ID and name, the amount of memory, the amount of
   disk space for the root partition and for the ephemeral partition, the swap,
   and the number of virtual CPUs for each flavor:

   .. code-block:: console

      $ openstack flavor list

#. To create a flavor, specify a name, ID, RAM size, disk size, and the number
   of vCPUs for the flavor, as follows:

   .. code-block:: console

      $ openstack flavor create FLAVOR_NAME --id FLAVOR_ID \
          --ram RAM_IN_MB --disk ROOT_DISK_IN_GB --vcpus NUMBER_OF_VCPUS

   .. note::

      Unique ID (integer or UUID) for the new flavor. If specifying 'auto', a
      UUID will be automatically generated.

   Here is an example that creates a public ``m1.extra_tiny`` flavor that
   automatically gets an ID assigned, with 256 MB memory, no disk space,
   and one VCPU.

   .. code-block:: console

      $ openstack flavor create --public m1.extra_tiny --id auto \
          --ram 256 --disk 0 --vcpus 1

#. If an individual user or group of users needs a custom flavor that you do
   not want other projects to have access to, you can create a private flavor.

   .. code-block:: console

      $ openstack flavor create --private m1.extra_tiny --id auto \
          --ram 256 --disk 0 --vcpus 1

   After you create a flavor, assign it to a project by specifying the flavor
   name or ID and the project ID:

   .. code-block:: console

      $ openstack flavor set --project PROJECT_ID m1.extra_tiny

   For a list of optional parameters, run this command:

   .. code-block:: console

      $ openstack help flavor create

#. In addition, you can set or unset properties, commonly referred to as
   "extra specs", for the existing flavor.
   The ``extra_specs`` metadata keys can influence the instance directly when
   it is launched. If a flavor sets the ``quota:vif_outbound_peak=65536``
   extra spec, the instance's outbound peak bandwidth I/O should be less than
   or equal to 512 Mbps. There are several aspects that can work for
   an instance including *CPU limits*, *Disk tuning*, *Bandwidth I/O*,
   *Watchdog behavior*, and *Random-number generator*.  For information about
   available metadata keys, see :doc:`/user/flavors`.

   For a list of optional parameters, run this command:

   .. code-block:: console

      $ openstack flavor set --help

Modify a flavor
---------------

Only the description of flavors can be modified (starting from microversion
2.55). To modify the description of a flavor, specify the flavor name or ID
and a new description as follows:

.. code-block:: console

   $ nova flavor-update FLAVOR DESCRIPTION

.. note::

   There are no commands to update a description of a flavor
   in the :command:`openstack` command currently (version 3.15.0).

Delete a flavor
---------------

To delete a flavor, specify the flavor name or ID as follows:

.. code-block:: console

   $ openstack flavor delete FLAVOR

Default Flavors
---------------

Previous versions of nova typically deployed with default flavors. This was
removed from Newton. The following table lists the default flavors for Mitaka
and earlier.

============  =========  ===============  ===============
 Flavor         VCPUs      Disk (in GB)     RAM (in MB)
============  =========  ===============  ===============
 m1.tiny        1          1                512
 m1.small       1          20               2048
 m1.medium      2          40               4096
 m1.large       4          80               8192
 m1.xlarge      8          160              16384
============  =========  ===============  ===============
