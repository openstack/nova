=======
Flavors
=======

In OpenStack, flavors define the compute, memory, and storage capacity of nova
computing instances. To put it simply, a flavor is an available hardware
configuration for a server. It defines the *size* of a virtual server that can
be launched.

.. note::

   Flavors can also determine on which compute host a flavor can be used to
   launch an instance. For information about customizing flavors, refer to
   :doc:`/admin/flavors`.

Overview
--------

A flavor consists of the following parameters:

Flavor ID
  Unique ID (integer or UUID) for the new flavor. This property is required. If
  specifying 'auto', a UUID will be automatically generated.

Name
  Name for the new flavor. This property is required.

  Historically, names were given a format `XX.SIZE_NAME`. These are typically
  not required, though some third party tools may rely on it.

VCPUs
  Number of virtual CPUs to use. This property is required.

Memory MB
  Amount of RAM to use (in megabytes). This property is required.

Root Disk GB
  Amount of disk space (in gigabytes) to use for the root (``/``) partition.
  This property is required.

  The root disk is an ephemeral disk that the base image is copied into. When
  booting from a persistent volume it is not used. The ``0`` size is a special
  case which uses the native base image size as the size of the ephemeral root
  volume. However, in this case the scheduler cannot select the compute
  host based on the virtual image size. As a result, ``0`` should only be used
  for volume booted instances or for testing purposes. Volume-backed instances
  can be enforced for flavors with zero root disk via the
  ``os_compute_api:servers:create:zero_disk_flavor`` policy rule.

Ephemeral Disk GB
  Amount of disk space (in gigabytes) to use for the ephemeral partition. This
  property is optional. If unspecified, the value is ``0`` by default.

  Ephemeral disks offer machine local disk storage linked to the lifecycle of a
  VM instance. When a VM is terminated, all data on the ephemeral disk is lost.
  Ephemeral disks are not included in any snapshots.

Swap
  Amount of swap space (in megabytes) to use. This property is optional. If
  unspecified, the value is ``0`` by default.

RXTX Factor (DEPRECATED)
  This value was only applicable when using the ``xen`` compute driver with the
  ``nova-network`` network driver. Since ``nova-network`` has been removed,
  this no longer applies and should not be specified. It will likely be
  removed in a future release. ``neutron`` users should refer to the
  :neutron-doc:`neutron QoS documentation <admin/config-qos.html>`

Is Public
  Boolean value that defines whether the flavor is available to all users or
  private to the project it was created in. This property is optional. In
  unspecified, the value is ``True`` by default.

  By default, a flavor is public and available to all projects. Private flavors
  are only accessible to those on the access list for a given project and are
  invisible to other projects.

Extra Specs
  Key and value pairs that define on which compute nodes a flavor can run.
  These are optional.

  Extra specs are generally used as scheduler hints for more advanced instance
  configuration. The key-value pairs used must correspond to well-known
  options.  For more information on the standardized extra specs available,
  :ref:`see below <flavors-extra-specs>`

Description
  A free form description of the flavor. Limited to 65535 characters in length.
  Only printable characters are allowed. Available starting in
  microversion 2.55.

.. _flavors-extra-specs:

Extra Specs
~~~~~~~~~~~

.. todo::

   This is now documented in :doc:`/configuration/extra-specs`, so this should
   be removed and the documentation moved to those specs.

.. _extra-specs-hardware-video-ram:

Hardware video RAM
  Specify ``hw_video:ram_max_mb`` to control the maximum RAM for the video
  image. Used in conjunction with the ``hw_video_ram`` image property.
  ``hw_video_ram`` must be less than or equal to ``hw_video:ram_max_mb``.

  This is currently supported by the libvirt and the vmware drivers.

  See https://libvirt.org/formatdomain.html#elementsVideo for more information
  on how this is used to set the ``vram`` attribute with the libvirt driver.

  See https://pubs.vmware.com/vi-sdk/visdk250/ReferenceGuide/vim.vm.device.VirtualVideoCard.html
  for more information on how this is used to set the ``videoRamSizeInKB`` attribute with
  the vmware driver.

.. _extra-specs-secure-boot:

Secure Boot
  :doc:`Secure Boot </admin/secure-boot>` can help ensure the bootloader used
  for your instances is trusted, preventing a possible attack vector.

  .. code:: console

     $ openstack flavor set FLAVOR-NAME \
         --property os:secure_boot=SECURE_BOOT_OPTION

  Valid ``SECURE_BOOT_OPTION`` values are:

  - ``required``: Enable Secure Boot for instances running with this flavor.
  - ``disabled`` or ``optional``: (default) Disable Secure Boot for instances
    running with this flavor.

  .. note::

     Supported by the libvirt driver.

  .. versionchanged:: 23.0.0 (Wallaby)

     Added support for secure boot to the libvirt driver.

.. _extra-specs-required-resources:

Custom resource classes and standard resource classes to override
  Specify custom resource classes to require or override quantity values of
  standard resource classes.

  The syntax of the extra spec is ``resources:<resource_class_name>=VALUE``
  (``VALUE`` is integer).
  The name of custom resource classes must start with ``CUSTOM_``.
  Standard resource classes to override are ``VCPU``, ``MEMORY_MB`` or
  ``DISK_GB``. In this case, you can disable scheduling based on standard
  resource classes by setting the value to ``0``.

  For example:

  - ``resources:CUSTOM_BAREMETAL_SMALL=1``
  - ``resources:VCPU=0``

  See :ironic-doc:`Create flavors for use with the Bare Metal service
  <install/configure-nova-flavors>` for more examples.

  .. versionadded:: 16.0.0 (Pike)

.. _extra-specs-required-traits:

Required traits
  Required traits allow specifying a server to build on a compute node with
  the set of traits specified in the flavor. The traits are associated with
  the resource provider that represents the compute node in the Placement
  API. See the resource provider traits API reference for more details:
  https://docs.openstack.org/api-ref/placement/#resource-provider-traits

  The syntax of the extra spec is ``trait:<trait_name>=required``, for
  example:

  - ``trait:HW_CPU_X86_AVX2=required``
  - ``trait:STORAGE_DISK_SSD=required``

  The scheduler will pass required traits to the
  ``GET /allocation_candidates`` endpoint in the Placement API to include
  only resource providers that can satisfy the required traits. In 17.0.0
  the only valid value is ``required``. In 18.0.0 ``forbidden`` is added (see
  below). Any other value will be considered
  invalid.

  Traits can be managed using the `osc-placement plugin`__.

  __ https://docs.openstack.org/osc-placement/latest/index.html

  .. versionadded:: 17.0.0 (Queens)

.. _extra-specs-forbidden-traits:

Forbidden traits
  Forbidden traits are similar to required traits, described above, but
  instead of specifying the set of traits that must be satisfied by a compute
  node, forbidden traits must **not** be present.

  The syntax of the extra spec is ``trait:<trait_name>=forbidden``, for
  example:

  - ``trait:HW_CPU_X86_AVX2=forbidden``
  - ``trait:STORAGE_DISK_SSD=forbidden``

  Traits can be managed using the `osc-placement plugin`__.

  __ https://docs.openstack.org/osc-placement/latest/index.html

  .. versionadded:: 18.0.0 (Rocky)

.. _extra-specs-numbered-resource-groupings:

Numbered groupings of resource classes and traits
  Specify numbered groupings of resource classes and traits.

  The syntax is as follows (``N`` and ``VALUE`` are integers):

  .. parsed-literal::

    resources\ *N*:*<resource_class_name>*\ =\ *VALUE*
    trait\ *N*:*<trait_name>*\ =required

  A given numbered ``resources`` or ``trait`` key may be repeated to
  specify multiple resources/traits in the same grouping,
  just as with the un-numbered syntax.

  Specify inter-group affinity policy via the ``group_policy`` key,
  which may have the following values:

  * ``isolate``: Different numbered request groups will be satisfied by
    *different* providers.
  * ``none``: Different numbered request groups may be satisfied
    by different providers *or* common providers.

  .. note::

      If more than one group is specified then the ``group_policy`` is
      mandatory in the request. However such groups might come from other
      sources than flavor extra_spec (e.g. from Neutron ports with QoS
      minimum bandwidth policy). If the flavor does not specify any groups
      and ``group_policy`` but more than one group is coming from other
      sources then nova will default the ``group_policy`` to ``none`` to
      avoid scheduler failure.

  For example, to create a server with the following VFs:

  * One SR-IOV virtual function (VF) on NET1 with bandwidth 10000 bytes/sec
  * One SR-IOV virtual function (VF) on NET2 with bandwidth 20000 bytes/sec
    on a *different* NIC with SSL acceleration

  It is specified in the extra specs as follows::

    resources1:SRIOV_NET_VF=1
    resources1:NET_EGRESS_BYTES_SEC=10000
    trait1:CUSTOM_PHYSNET_NET1=required
    resources2:SRIOV_NET_VF=1
    resources2:NET_EGRESS_BYTES_SEC:20000
    trait2:CUSTOM_PHYSNET_NET2=required
    trait2:HW_NIC_ACCEL_SSL=required
    group_policy=isolate

  See `Granular Resource Request Syntax`__ for more details.

  __ https://specs.openstack.org/openstack/nova-specs/specs/rocky/implemented/granular-resource-requests.html

  .. versionadded:: 18.0.0 (Rocky)
