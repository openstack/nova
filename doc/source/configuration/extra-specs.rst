===========
Extra Specs
===========

The following is an overview of all extra specs recognized by nova in its
default configuration.

.. note::

    Other services and virt drivers may provide additional extra specs not
    listed here. In addition, it is possible to register your own extra specs.
    For more information on the latter, refer to :doc:`/user/filter-scheduler`.

Placement
---------

The following extra specs are used during scheduling to modify the request sent
to placement.

``resources``
~~~~~~~~~~~~~

The following extra specs are used to request an amount of the specified
resource from placement when scheduling. All extra specs expect an integer
value.

.. note::

   Not all of the resource types listed below are supported by all virt
   drivers.

.. extra-specs:: resources
   :summary:

``trait``
~~~~~~~~~

The following extra specs are used to request a specified trait from placement
when scheduling. All extra specs expect one of the following values:

- ``required``
- ``forbidden``

.. note::

   Not all of the traits listed below are supported by all virt drivers.

.. extra-specs:: trait
   :summary:

Scheduler Filters
-----------------

The following extra specs are specific to various in-tree scheduler filters.

``aggregate_instance_extra_specs``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following extra specs are used to specify metadata that must be present on
the aggregate of a host. If this metadata is not present or does not match the
expected value, the aggregate and all hosts within in will be rejected.

Requires the ``AggregateInstanceExtraSpecsFilter`` scheduler filter.

.. extra-specs:: aggregate_instance_extra_specs

``capabilities``
~~~~~~~~~~~~~~~~

The following extra specs are used to specify a host capability that must be
provided by the host compute service. If this capability is not present or does
not match the expected value, the host will be rejected.

Requires the ``ComputeCapabilitiesFilter`` scheduler filter.

All extra specs expect similar types of values:

* ``=`` (equal to or greater than as a number; same as vcpus case)
* ``==`` (equal to as a number)
* ``!=`` (not equal to as a number)
* ``>=`` (greater than or equal to as a number)
* ``<=`` (less than or equal to as a number)
* ``s==`` (equal to as a string)
* ``s!=`` (not equal to as a string)
* ``s>=`` (greater than or equal to as a string)
* ``s>`` (greater than as a string)
* ``s<=`` (less than or equal to as a string)
* ``s<`` (less than as a string)
* ``<in>`` (substring)
* ``<all-in>`` (all elements contained in collection)
* ``<or>`` (find one of these)
* A specific value, e.g. ``true``, ``123``, ``testing``

Examples are: ``>= 5``, ``s== 2.1.0``, ``<in> gcc``, ``<all-in> aes mmx``, and
``<or> fpu <or> gpu``

.. note::

   Not all operators will apply to all types of values. For example, the ``==``
   operator should not be used for a string value - use ``s==`` instead.

.. extra-specs:: capabilities
   :summary:

Virt driver
-----------

The following extra specs are used as hints to configure internals of a
instance, from the bus used for paravirtualized devices to the amount of a
physical device to passthrough to the instance. Most of these are virt
driver-specific.

``quota``
~~~~~~~~~

The following extra specs are used to configure quotas for various
paravirtualized devices.

They are only supported by the libvirt virt driver.

.. extra-specs:: quota

``accel``
~~~~~~~~~

The following extra specs are used to configure attachment of various
accelerators to an instance. For more information, refer to :cyborg-doc:`the
Cyborg documentation <>`.

They are only supported by the libvirt virt driver.

.. extra-specs:: accel

``pci_passthrough``
~~~~~~~~~~~~~~~~~~~

The following extra specs are used to configure passthrough of a host PCI
device to an instance. This requires prior host configuration. For more
information, refer to :doc:`/admin/pci-passthrough`.

They are only supported by the libvirt virt driver.

.. extra-specs:: pci_passthrough

``hw``
~~~~~~

The following extra specs are used to configure various attributes of
instances. Some of the extra specs act as feature flags, while others tweak for
example the guest-visible CPU topology of the instance.

Except where otherwise stated, they are only supported by the libvirt virt
driver.

.. extra-specs:: hw

``hw_rng``
~~~~~~~~~~

The following extra specs are used to configure a random number generator for
an instance.

They are only supported by the libvirt virt driver.

.. extra-specs:: hw_rng

``hw_video``
~~~~~~~~~~~~

The following extra specs are used to configure attributes of the default guest
video device.

They are only supported by the libvirt virt driver.

.. extra-specs:: hw_video

``os``
~~~~~~

The following extra specs are used to configure various attributes of
instances when using the HyperV virt driver.

They are only supported by the HyperV virt driver.

.. extra-specs:: os

``powervm``
~~~~~~~~~~~

The following extra specs are used to configure various attributes of
instances when using the PowerVM virt driver.

They are only supported by the PowerVM virt driver.

.. extra-specs:: powervm

``vmware``
~~~~~~~~~~

The following extra specs are used to configure various attributes of
instances when using the VMWare virt driver.

They are only supported by the VMWare virt driver.

.. extra-specs:: vmware

Others (uncategorized)
----------------------

The following extra specs are not part of a group.

.. extra-specs::
