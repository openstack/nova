=============================================
Attaching virtual persistent memory to guests
=============================================

.. versionadded:: 20.0.0 (Train)

Starting in the 20.0.0 (Train) release, the virtual persistent memory (vPMEM)
feature in Nova allows a deployment using the libvirt compute driver to provide
vPMEMs for instances using physical persistent memory (PMEM) that can provide
virtual devices.

PMEM must be partitioned into `PMEM namespaces`_ for applications to use.
This vPMEM feature only uses PMEM namespaces in ``devdax`` mode as QEMU
`vPMEM backends`_. If you want to dive into related notions, the document
`NVDIMM Linux kernel document`_ is recommended.

To enable vPMEMs, follow the steps below.


Dependencies
------------

The following are required to support the vPMEM feature:

* Persistent Memory Hardware

  One such product is Intel® Optane™ DC Persistent Memory.
  `ipmctl`_ is used to configure it.

* Linux Kernel version >= 4.18 with the following modules loaded:

  ``dax_pmem``, ``nd_pmem``, ``device_dax``, ``nd_btt``

.. note::

  NVDIMM support is present in the Linux Kernel v4.0 or newer. It is
  recommended to use Kernel version 4.2 or later since `NVDIMM support
  <https://docs.pmem.io/persistent-memory/getting-started-guide/creating-development-environments/linux-environments>`_
  is enabled by default. We met some bugs in older versions, and we have
  done all verification works with OpenStack on 4.18 version, so 4.18
  version and newer will probably guarantee its functionality.

* QEMU version >= 3.1.0

* Libvirt version >= 5.0.0

* `ndctl`_ version >= 62

* daxio version >= 1.6

The vPMEM feature has been verified under the software and hardware listed above.


Configure PMEM namespaces (Compute)
-----------------------------------

#. Create PMEM namespaces as `vPMEM backends`_ using the `ndctl`_ utility.

   For example, to create a 30GiB namespace named ``ns3``:

   .. code-block:: console

      $ sudo ndctl create-namespace -s 30G -m devdax -M mem -n ns3
      {
        "dev":"namespace1.0",
        "mode":"devdax",
        "map":"mem",
        "size":"30.00 GiB (32.21 GB)",
        "uuid":"937e9269-512b-4f65-9ac6-b74b61075c11",
        "raw_uuid":"17760832-a062-4aef-9d3b-95ea32038066",
        "daxregion":{
          "id":1,
          "size":"30.00 GiB (32.21 GB)",
          "align":2097152,
          "devices":[
          {
            "chardev":"dax1.0",
            "size":"30.00 GiB (32.21 GB)"
          }
          ]
        },
        "name":"ns3",
        "numa_node":1
      }

   Then list the available PMEM namespaces on the host:

   .. code-block:: console

      $ ndctl list -X
      [
        {
          ...
          "size":6440353792,
          ...
          "name":"ns0",
          ...
        },
        {
          ...
          "size":6440353792,
          ...
          "name":"ns1",
          ...
        },
        {
          ...
          "size":6440353792,
          ...
          "name":"ns2",
          ...
        },
        {
          ...
          "size":32210157568,
          ...
          "name":"ns3",
          ...
        }
      ]

#. Specify which PMEM namespaces should be available to instances.

   Edit :oslo.config:option:`libvirt.pmem_namespaces`:

   .. code-block:: ini

      [libvirt]
      # pmem_namespaces=$LABEL:$NSNAME[|$NSNAME][,$LABEL:$NSNAME[|$NSNAME]]
      pmem_namespaces = 6GB:ns0|ns1|ns2,LARGE:ns3

   Configured PMEM namespaces must have already been created on the host as
   described above. The conf syntax allows the admin to associate one or more
   namespace ``$NSNAME``\ s with an arbitrary ``$LABEL`` that can subsequently
   be used in a flavor to request one of those namespaces. It is recommended,
   but not required, for namespaces under a single ``$LABEL`` to be the same
   size.

#. Restart the ``nova-compute`` service.

   Nova will invoke `ndctl`_ to identify the configured PMEM namespaces, and
   report vPMEM resources to placement.


Configure a flavor
------------------

Specify a comma-separated list of the ``$LABEL``\ s from
:oslo.config:option:`libvirt.pmem_namespaces` to the flavor's ``hw:pmem``
property. Note that multiple instances of the same label are permitted:

.. code-block:: console

   $ openstack flavor set --property hw:pmem='6GB' my_flavor
   $ openstack flavor set --property hw:pmem='6GB,LARGE' my_flavor_large
   $ openstack flavor set --property hw:pmem='6GB,6GB' m1.medium

.. note:: If a NUMA topology is specified, all vPMEM devices will be put on
          guest NUMA node 0; otherwise nova will generate one NUMA node
          automatically for the guest.

Based on the above examples, an ``openstack server create`` request with
``my_flavor_large`` will spawn an instance with two vPMEMs. One, corresponding
to the ``LARGE`` label, will be ``ns3``; the other, corresponding to the ``6G``
label, will be arbitrarily chosen from ``ns0``, ``ns1``, or ``ns2``.

.. note::

  Using vPMEM inside a virtual machine requires the following:

  * Guest kernel version 4.18 or higher;
  * The ``dax_pmem``, ``nd_pmem``, ``device_dax``, and ``nd_btt`` kernel
    modules;
  * The `ndctl`_ utility.

.. note:: When resizing an instance with vPMEMs, the vPMEM data won't be
          migrated.


Verify inventories and allocations
----------------------------------
This section describes how to check that:

* vPMEM inventories were created correctly in placement, validating the
  `configuration described above <#configure-pmem-namespaces-compute>`_.
* allocations were created correctly in placement for instances spawned from
  `flavors configured with vPMEMs <#configure-a-flavor>`_.

.. note::

  Inventories and allocations related to vPMEM resource classes are on the
  root resource provider related to the compute node.

#. Get the list of resource providers

   .. code-block:: console

      $ openstack resource provider list
      +--------------------------------------+--------+------------+
      | uuid                                 | name   | generation |
      +--------------------------------------+--------+------------+
      | 1bc545f9-891f-4930-ab2b-88a56078f4be | host-1 |         47 |
      | 7d994aef-680d-43d4-9325-a67c807e648e | host-2 |         67 |
      --------------------------------------+---------+------------+

#. Check the inventory of each resource provider to see resource classes

   Each ``$LABEL`` configured in :oslo.config:option:`libvirt.pmem_namespaces`
   is used to generate a resource class named ``CUSTOM_PMEM_NAMESPACE_$LABEL``.
   Nova will report to Placement the number of vPMEM namespaces configured for
   each ``$LABEL``. For example, assuming ``host-1`` was configured as
   described above:

   .. code-block:: console

      $ openstack resource provider inventory list 1bc545f9-891f-4930-ab2b-88a56078f4be
      +-----------------------------+------------------+----------+----------+-----------+----------+--------+
      | resource_class              | allocation_ratio | max_unit | reserved | step_size | min_unit |  total |
      +-----------------------------+------------------+----------+----------+-----------+----------+--------+
      | VCPU                        |             16.0 |       64 |        0 |         1 |        1 |     64 |
      | MEMORY_MB                   |              1.5 |   190604 |      512 |         1 |        1 | 190604 |
      | CUSTOM_PMEM_NAMESPACE_LARGE |              1.0 |        1 |        0 |         1 |        1 |      1 |
      | CUSTOM_PMEM_NAMESPACE_6GB   |              1.0 |        3 |        0 |         1 |        1 |      3 |
      | DISK_GB                     |              1.0 |      439 |        0 |         1 |        1 |    439 |
      +-----------------------------+------------------+----------+----------+-----------+----------+--------+

   Here you can see the vPMEM resource classes prefixed with
   ``CUSTOM_PMEM_NAMESPACE_``. The ``LARGE`` label was configured with one
   namespace (``ns3``), so it has an inventory of ``1``. Since the ``6GB``
   label was configured with three namespaces (``ns0``, ``ns1``, and ``ns2``),
   the ``CUSTOM_PMEM_NAMESPACE_6GB`` inventory has a ``total`` and ``max_unit``
   of ``3``.

#. Check allocations for each server that is using vPMEMs

   .. code-block:: console

      $ openstack server list
      +--------------------------------------+----------------------+--------+-------------------+---------------+-----------------+
      | ID                                   | Name                 | Status | Networks          | Image         | Flavor          |
      +--------------------------------------+----------------------+--------+-------------------+---------------+-----------------+
      | 41d3e139-de5c-40fd-9d82-016b72f2ba1d | server-with-2-vpmems | ACTIVE | private=10.0.0.24 | ubuntu-bionic | my_flavor_large |
      | a616a7f6-b285-4adf-a885-dd8426dd9e6a | server-with-1-vpmem  | ACTIVE | private=10.0.0.13 | ubuntu-bionic | my_flavor       |
      +--------------------------------------+----------------------+--------+-------------------+---------------+-----------------+

      $ openstack resource provider allocation show 41d3e139-de5c-40fd-9d82-016b72f2ba1d
      +--------------------------------------+------------+------------------------------------------------------------------------------------------------------------------------+
      | resource_provider                    | generation | resources                                                                                                              |
      +--------------------------------------+------------+------------------------------------------------------------------------------------------------------------------------+
      | 1bc545f9-891f-4930-ab2b-88a56078f4be |         49 | {u'MEMORY_MB': 32768, u'VCPU': 16, u'DISK_GB': 20, u'CUSTOM_PMEM_NAMESPACE_6GB': 1, u'CUSTOM_PMEM_NAMESPACE_LARGE': 1} |
      +--------------------------------------+------------+------------------------------------------------------------------------------------------------------------------------+

      $ openstack resource provider allocation show a616a7f6-b285-4adf-a885-dd8426dd9e6a
      +--------------------------------------+------------+-----------------------------------------------------------------------------------+
      | resource_provider                    | generation | resources                                                                         |
      +--------------------------------------+------------+-----------------------------------------------------------------------------------+
      | 1bc545f9-891f-4930-ab2b-88a56078f4be |         49 | {u'MEMORY_MB': 8192, u'VCPU': 8, u'DISK_GB': 20, u'CUSTOM_PMEM_NAMESPACE_6GB': 1} |
      +--------------------------------------+------------+-----------------------------------------------------------------------------------+

   In this example, two servers were created. ``server-with-2-vpmems`` used
   ``my_flavor_large`` asking for one ``6GB`` vPMEM and one ``LARGE`` vPMEM.
   ``server-with-1-vpmem`` used ``my_flavor`` asking for a single ``6GB``
   vPMEM.


.. _`PMEM namespaces`: http://pmem.io/ndctl/ndctl-create-namespace.html
.. _`vPMEM backends`: https://github.com/qemu/qemu/blob/19b599f7664b2ebfd0f405fb79c14dd241557452/docs/nvdimm.txt#L145
.. _`NVDIMM Linux kernel document`: https://www.kernel.org/doc/Documentation/nvdimm/nvdimm.txt
.. _`ipmctl`: https://software.intel.com/en-us/articles/quick-start-guide-configure-intel-optane-dc-persistent-memory-on-linux
.. _`ndctl`: http://pmem.io/ndctl/
