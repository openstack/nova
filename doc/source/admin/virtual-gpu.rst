=======================================
Attaching virtual GPU devices to guests
=======================================

The virtual GPU feature in Nova allows a deployment to provide specific GPU
types for instances using physical GPUs that can provide virtual devices.

For example, a single `Intel GVT-g`_  or a `NVIDIA GRID vGPU`_ physical
Graphics Processing Unit (pGPU) can be virtualized as multiple virtual Graphics
Processing Units (vGPUs) if the hypervisor supports the hardware driver and has
the capability to create guests using those virtual devices.

This feature is highly dependent on the hypervisor, its version and the
physical devices present on the host. In addition, the vendor's vGPU driver software
must be installed and configured on the host at the same time.

Hypervisor-specific caveats are mentioned in the `Caveats`_ section.

To enable virtual GPUs, follow the steps below:

#. `Enable GPU types (Compute)`_

#. `Configure a flavor (Controller)`_


Enable GPU types (Compute)
--------------------------

#. Specify which specific GPU type(s) the instances would get.

   Edit :oslo.config:option:`devices.enabled_vgpu_types`:

   .. code-block:: ini

      [devices]
      enabled_vgpu_types = nvidia-35

   If you want to support more than a single GPU type, you need to provide a
   separate configuration section for each device. For example:

   .. code-block:: ini

      [devices]
      enabled_vgpu_types = nvidia-35, nvidia-36

      [vgpu_nvidia-35]
      device_addresses = 0000:84:00.0,0000:85:00.0

      [vgpu_nvidia-36]
      device_addresses = 0000:86:00.0

   where you have to define which physical GPUs are supported per GPU type.

   If the same PCI address is provided for two different types, nova-compute
   will refuse to start and issue a specific error in the logs.

   To know which specific type(s) to mention, please refer to `How to discover
   a GPU type`_.

   .. versionchanged:: 21.0.0

      Supporting multiple GPU types is only supported by the Ussuri release and
      later versions.

#. Restart the ``nova-compute`` service.


   .. warning::

        Changing the type is possible but since existing physical GPUs can't
        address multiple guests having different types, that will make Nova
        return you a NoValidHost if existing instances with the original type
        still exist. Accordingly, it's highly recommended to instead deploy the
        new type to new compute nodes that don't already have workloads and
        rebuild instances on the nodes that need to change types.


Configure a flavor (Controller)
-------------------------------

Configure a flavor to request one virtual GPU:

.. code-block:: console

   $ openstack flavor set vgpu_1 --property "resources:VGPU=1"

.. note::

       As of the Queens release, all hypervisors that support virtual GPUs
       only accept a single virtual GPU per instance.

The enabled vGPU types on the compute hosts are not exposed to API users.
Flavors configured for vGPU support can be tied to host aggregates as a means
to properly schedule those flavors onto the compute hosts that support them.
See :doc:`/admin/aggregates` for more information.

Create instances with virtual GPU devices
-----------------------------------------

The ``nova-scheduler`` selects a destination host that has vGPU devices
available by calling the Placement API for a specific VGPU resource class
provided by compute nodes.

.. code-block:: console

   $ openstack server create --flavor vgpu_1 --image cirros-0.3.5-x86_64-uec --wait test-vgpu

.. note::

   As of the Queens release, only the *FilterScheduler* scheduler driver
   uses the Placement API.


How to discover a GPU type
--------------------------

Depending on your hypervisor:

- For libvirt, virtual GPUs are seen as mediated devices. Physical PCI devices
  (the graphic card here) supporting virtual GPUs propose mediated device
  (mdev) types. Since mediated devices are supported by the Linux kernel
  through sysfs files after installing the vendor's virtual GPUs driver
  software, you can see the required properties as follows:

  .. code-block:: console

     $ ls /sys/class/mdev_bus/*/mdev_supported_types
     /sys/class/mdev_bus/0000:84:00.0/mdev_supported_types:
     nvidia-35  nvidia-36  nvidia-37  nvidia-38  nvidia-39  nvidia-40  nvidia-41  nvidia-42  nvidia-43  nvidia-44  nvidia-45

     /sys/class/mdev_bus/0000:85:00.0/mdev_supported_types:
     nvidia-35  nvidia-36  nvidia-37  nvidia-38  nvidia-39  nvidia-40  nvidia-41  nvidia-42  nvidia-43  nvidia-44  nvidia-45

     /sys/class/mdev_bus/0000:86:00.0/mdev_supported_types:
     nvidia-35  nvidia-36  nvidia-37  nvidia-38  nvidia-39  nvidia-40  nvidia-41  nvidia-42  nvidia-43  nvidia-44  nvidia-45

     /sys/class/mdev_bus/0000:87:00.0/mdev_supported_types:
     nvidia-35  nvidia-36  nvidia-37  nvidia-38  nvidia-39  nvidia-40  nvidia-41  nvidia-42  nvidia-43  nvidia-44  nvidia-45


- For XenServer, virtual GPU types are created by XenServer at startup
  depending on the available hardware and config files present in dom0.
  You can run the command of ``xe vgpu-type-list`` from dom0 to get the
  available vGPU types. The value for the field of ``model-name ( RO):``
  is the vGPU type's name which can be used to set the nova config option
  ``[devices]/enabled_vgpu_types``. See the following example:

  .. code-block:: console

    [root@trailblazer-2 ~]# xe vgpu-type-list
    uuid ( RO)              : 78d2d963-41d6-4130-8842-aedbc559709f
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-8Q
             max-heads ( RO): 4
        max-resolution ( RO): 4096x2160


    uuid ( RO)              : a1bb1692-8ce3-4577-a611-6b4b8f35a5c9
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-0Q
             max-heads ( RO): 2
        max-resolution ( RO): 2560x1600


    uuid ( RO)              : 69d03200-49eb-4002-b661-824aec4fd26f
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-2A
             max-heads ( RO): 1
        max-resolution ( RO): 1280x1024


    uuid ( RO)              : c58b1007-8b47-4336-95aa-981a5634d03d
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-4Q
             max-heads ( RO): 4
        max-resolution ( RO): 4096x2160


    uuid ( RO)              : 292a2b20-887f-4a13-b310-98a75c53b61f
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-2Q
             max-heads ( RO): 4
        max-resolution ( RO): 4096x2160


    uuid ( RO)              : d377db6b-a068-4a98-92a8-f94bd8d6cc5d
           vendor-name ( RO): NVIDIA Corporation
            model-name ( RO): GRID M60-0B
             max-heads ( RO): 2
        max-resolution ( RO): 2560x1600

    ...

Checking allocations and inventories for virtual GPUs
-----------------------------------------------------

.. note::

   The information below is only valid from the 19.0.0 Stein release and only
   for the libvirt driver. Before this release or when using the Xen driver,
   inventories and allocations related to a ``VGPU`` resource class are still
   on the root resource provider related to the compute node.
   If upgrading from Rocky and using the libvirt driver, ``VGPU`` inventory and
   allocations are moved to child resource providers that represent actual
   physical GPUs.

The examples you will see are using the `osc-placement plugin`_ for
OpenStackClient. For details on specific commands, see its documentation.

#. Get the list of resource providers

   .. code-block:: console

     $ openstack resource provider list
     +--------------------------------------+---------------------------------------------------------+------------+
     | uuid                                 | name                                                    | generation |
     +--------------------------------------+---------------------------------------------------------+------------+
     | 5958a366-3cad-416a-a2c9-cfbb5a472287 | virtlab606.xxxxxxxxxxxxxxxxxxxxxxxxxxx                  |          7 |
     | fc9b9287-ef5e-4408-aced-d5577560160c | virtlab606.xxxxxxxxxxxxxxxxxxxxxxxxxxx_pci_0000_86_00_0 |          2 |
     | e2f8607b-0683-4141-a8af-f5e20682e28c | virtlab606.xxxxxxxxxxxxxxxxxxxxxxxxxxx_pci_0000_85_00_0 |          3 |
     | 85dd4837-76f9-41f2-9f19-df386017d8a0 | virtlab606.xxxxxxxxxxxxxxxxxxxxxxxxxxx_pci_0000_87_00_0 |          2 |
     | 7033d860-8d8a-4963-8555-0aa902a08653 | virtlab606.xxxxxxxxxxxxxxxxxxxxxxxxxxx_pci_0000_84_00_0 |          2 |
     +--------------------------------------+---------------------------------------------------------+------------+

   In this example, we see the root resource provider
   ``5958a366-3cad-416a-a2c9-cfbb5a472287`` with four other resource providers
   that are its children and where each of them corresponds to a single
   physical GPU.

#. Check the inventory of each resource provider to see resource classes

   .. code-block:: console

     $ openstack resource provider inventory list 5958a366-3cad-416a-a2c9-cfbb5a472287
     +----------------+------------------+----------+----------+-----------+----------+-------+
     | resource_class | allocation_ratio | max_unit | reserved | step_size | min_unit | total |
     +----------------+------------------+----------+----------+-----------+----------+-------+
     | VCPU           |             16.0 |       48 |        0 |         1 |        1 |    48 |
     | MEMORY_MB      |              1.5 |    65442 |      512 |         1 |        1 | 65442 |
     | DISK_GB        |              1.0 |       49 |        0 |         1 |        1 |    49 |
     +----------------+------------------+----------+----------+-----------+----------+-------+
     $ openstack resource provider inventory list e2f8607b-0683-4141-a8af-f5e20682e28c
     +----------------+------------------+----------+----------+-----------+----------+-------+
     | resource_class | allocation_ratio | max_unit | reserved | step_size | min_unit | total |
     +----------------+------------------+----------+----------+-----------+----------+-------+
     | VGPU           |              1.0 |       16 |        0 |         1 |        1 |    16 |
     +----------------+------------------+----------+----------+-----------+----------+-------+

   Here you can see a ``VGPU`` inventory on the child resource provider while
   other resource class inventories are still located on the root resource
   provider.

#. Check allocations for each server that is using virtual GPUs

   .. code-block:: console

     $ openstack server list
     +--------------------------------------+-------+--------+---------------------------------------------------------+--------------------------+--------+
     | ID                                   | Name  | Status | Networks                                                | Image                    | Flavor |
     +--------------------------------------+-------+--------+---------------------------------------------------------+--------------------------+--------+
     | 5294f726-33d5-472a-bef1-9e19bb41626d | vgpu2 | ACTIVE | private=10.0.0.14, fd45:cdad:c431:0:f816:3eff:fe78:a748 | cirros-0.4.0-x86_64-disk | vgpu   |
     | a6811fc2-cec8-4f1d-baea-e2c6339a9697 | vgpu1 | ACTIVE | private=10.0.0.34, fd45:cdad:c431:0:f816:3eff:fe54:cc8f | cirros-0.4.0-x86_64-disk | vgpu   |
     +--------------------------------------+-------+--------+---------------------------------------------------------+--------------------------+--------+

     $ openstack resource provider allocation show 5294f726-33d5-472a-bef1-9e19bb41626d
     +--------------------------------------+------------+------------------------------------------------+
     | resource_provider                    | generation | resources                                      |
     +--------------------------------------+------------+------------------------------------------------+
     | 5958a366-3cad-416a-a2c9-cfbb5a472287 |          8 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} |
     | 7033d860-8d8a-4963-8555-0aa902a08653 |          3 | {u'VGPU': 1}                                   |
     +--------------------------------------+------------+------------------------------------------------+

     $ openstack resource provider allocation show a6811fc2-cec8-4f1d-baea-e2c6339a9697
     +--------------------------------------+------------+------------------------------------------------+
     | resource_provider                    | generation | resources                                      |
     +--------------------------------------+------------+------------------------------------------------+
     | e2f8607b-0683-4141-a8af-f5e20682e28c |          3 | {u'VGPU': 1}                                   |
     | 5958a366-3cad-416a-a2c9-cfbb5a472287 |          8 | {u'VCPU': 1, u'MEMORY_MB': 512, u'DISK_GB': 1} |
     +--------------------------------------+------------+------------------------------------------------+

   In this example, two servers were created using a flavor asking for 1
   ``VGPU``, so when looking at the allocations for each consumer UUID (which
   is the server UUID), you can see that VGPU allocation is against the child
   resource provider while other allocations are for the root resource
   provider. Here, that means that the virtual GPU used by
   ``a6811fc2-cec8-4f1d-baea-e2c6339a9697`` is actually provided by the
   physical GPU having the PCI ID ``0000:85:00.0``.


(Optional) Provide custom traits for multiple GPU types
-------------------------------------------------------

Since operators want to support different GPU types per compute, it would be
nice to have flavors asking for a specific GPU type. This is now possible
using custom traits by decorating child Resource Providers that correspond
to physical GPUs.

.. note::

   Possible improvements in a future release could consist of providing
   automatic tagging of Resource Providers with standard traits corresponding
   to versioned mapping of public GPU types. For the moment, this has to be
   done manually.

#. Get the list of resource providers

   See `Checking allocations and inventories for virtual GPUs`_ first for getting
   the list of Resource Providers that support a ``VGPU`` resource class.

#. Define custom traits that will correspond for each to a GPU type

   .. code-block:: console

      $ openstack --os-placement-api-version 1.6 trait create CUSTOM_NVIDIA_11

   In this example, we ask to create a custom trait named ``CUSTOM_NVIDIA_11``.

#. Add the corresponding trait to the Resource Provider matching the GPU

   .. code-block:: console

      $ openstack --os-placement-api-version 1.6 resource provider trait set \
          --trait CUSTOM_NVIDIA_11 e2f8607b-0683-4141-a8af-f5e20682e28c

   In this case, the trait ``CUSTOM_NVIDIA_11`` will be added to the Resource
   Provider with the UUID ``e2f8607b-0683-4141-a8af-f5e20682e28c`` that
   corresponds to the PCI address ``0000:85:00:0`` as shown above.

#. Amend the flavor to add a requested trait

   .. code-block:: console

      $ openstack flavor set --property trait:CUSTOM_NVIDIA_11=required vgpu_1

   In this example, we add the ``CUSTOM_NVIDIA_11`` trait as a required
   information for the ``vgpu_1`` flavor we created earlier.

   This will allow the Placement service to only return the Resource Providers
   matching this trait so only the GPUs that were decorated with will be checked
   for this flavor.


Caveats
-------

.. note::

   This information is correct as of the 17.0.0 Queens release. Where
   improvements have been made or issues fixed, they are noted per item.

For libvirt:

* Suspending a guest that has vGPUs doesn't yet work because of a libvirt
  limitation (it can't hot-unplug mediated devices from a guest). Workarounds
  using other instance actions (like snapshotting the instance or shelving it)
  are recommended until libvirt gains mdev hot-unplug support. If a user
  attempts to suspend the instance, the libvirt driver will raise an exception
  that will cause the instance to be set back to ACTIVE. The ``suspend`` action
  in the ``os-instance-actions`` API will have an *Error* state.

* Resizing an instance with a new flavor that has vGPU resources doesn't
  allocate those vGPUs to the instance (the instance is created without
  vGPU resources). The proposed workaround is to rebuild the instance after
  resizing it. The rebuild operation allocates vGPUS to the instance.

  .. versionchanged:: 21.0.0

     This has been resolved in the Ussuri release. See `bug 1778563`_.

* Cold migrating an instance to another host will have the same problem as
  resize. If you want to migrate an instance, make sure to rebuild it after the
  migration.

  .. versionchanged:: 21.0.0

     This has been resolved in the Ussuri release. See `bug 1778563`_.

* Rescue images do not use vGPUs. An instance being rescued does not keep its
  vGPUs during rescue. During that time, another instance can receive those
  vGPUs. This is a known issue. The recommended workaround is to rebuild an
  instance immediately after rescue. However, rebuilding the rescued instance
  only helps if there are other free vGPUs on the host.

  .. versionchanged:: 18.0.0

     This has been resolved in the Rocky release. See `bug 1762688`_.

For XenServer:

* Suspend and live migration with vGPUs attached depends on support from the
  underlying XenServer version. Please see XenServer release notes for up to
  date information on when a hypervisor supporting live migration and
  suspend/resume with vGPUs is available. If a suspend or live migrate operation
  is attempted with a XenServer version that does not support that operation, an
  internal exception will occur that will cause nova setting the instance to
  be in ERROR status. You can use the command of
  ``openstack server set --state active <server>`` to set it back to ACTIVE.

* Resizing an instance with a new flavor that has vGPU resources doesn't
  allocate those vGPUs to the instance (the instance is created without
  vGPU resources). The proposed workaround is to rebuild the instance after
  resizing it. The rebuild operation allocates vGPUS to the instance.

* Cold migrating an instance to another host will have the same problem as
  resize. If you want to migrate an instance, make sure to rebuild it after the
  migration.

* Multiple GPU types per compute is not supported by the XenServer driver.

.. _bug 1778563: https://bugs.launchpad.net/nova/+bug/1778563
.. _bug 1762688: https://bugs.launchpad.net/nova/+bug/1762688

.. Links
.. _Intel GVT-g: https://01.org/igvt-g
.. _NVIDIA GRID vGPU: http://docs.nvidia.com/grid/5.0/pdf/grid-vgpu-user-guide.pdf
.. _osc-placement plugin: https://docs.openstack.org/osc-placement/latest/index.html
