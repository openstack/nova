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
physical devices present on the host.

.. important:: As of the Queens release, there is no upstream continuous
               integration testing with a hardware environment that has virtual
               GPUs and therefore this feature is considered experimental.

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

   .. note::

         As of the Queens release, Nova only supports a single type. If more
         than one vGPU type is specified (as a comma-separated list), only the
         first one will be used.

   To know which specific type(s) to mention, please refer to `How to discover
   a GPU type`_.

#. Restart the ``nova-compute`` service.

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
See the `host aggregates`_ guide for more information.

.. _host aggregates: https://docs.openstack.org/nova/latest/user/aggregates.html

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
  through sysfs files, you can see the required properties as follows:

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


.. todo:: Discovering GPU types in Xen.

Caveats
-------

.. note::

       All the caveats are related to the Queens release

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

* Cold migrating an instance to another host will have the same problem as
  resize. If you want to migrate an instance, make sure to rebuild it after the
  migration.

* Rescue images do not use vGPUs. An instance being rescued does not keep its
  vGPUs during rescue. During that time, another instance can receive those
  vGPUs. This is a known issue. The recommended workaround is to rebuild an
  instance immediately after rescue. However, rebuilding the rescued instance
  only helps if there are other free vGPUs on the host.

.. todo:: Xen caveats.

.. Links
.. _Intel GVT-g: https://01.org/igvt-g
.. _NVIDIA GRID vGPU: http://docs.nvidia.com/grid/5.0/pdf/grid-vgpu-user-guide.pdf
