..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

======================================================================
hw_machine_type - Configuring and updating QEMU instance machine types
======================================================================

.. versionadded:: 12.0.0 (Liberty)

.. versionchanged:: 23.0.0 (Wallaby)

   The libvirt driver now records the machine type of an instance at start up
   allowing the ``[libvirt]hw_machine_type`` configurable to change over time
   without impacting existing instances.

   Added ``nova-manage`` commands to control the machine_type of an instance.

.. versionchanged:: 25.0.0 (Yoga)

   Added ``nova-manage`` commands to set the image properties of an instance.

.. note::

   The following only applies to environments using libvirt compute hosts.

Introduction
------------

QEMU's machine type concept can be thought of as a virtual chipset that
provides certain default devices (e.g. PCIe graphics card, Ethernet controller,
SATA controller, etc).  QEMU supports two main variants of "machine type" for
x86 hosts: (a) ``pc``, which corresponds to Intel's I440FX chipset (released in
1996) and (b) ``q35``, which corresponds to Intel's 82Q35 chipset (released in
2007).  For AArch64 hosts, the machine type is called: ``virt``.

The ``pc`` machine type is considered legacy, and does not support many modern
features.  Although at this time of writing, upstream QEMU has not reached an
agreement to remove new versioned variants of the ``pc`` machine type, some
long-term stable Linux distributions (CentOS, RHEL, possibly others) are moving
to support ``q35`` only.

Configure
---------

For end users the machine type of an instance is controlled by the selection of
an image with the `hw_machine_type image metadata property`__ set.

.. __: https://docs.openstack.org/glance/latest/admin/useful-image-properties.html

.. code-block:: shell

    $ openstack image set --property hw_machine_type=q35 $IMAGE

The libvirt virt driver supports the configuration of a per compute host
default machine type via the  :oslo.config:option:`libvirt.hw_machine_type`
option.  Providing a default machine type per host architecture to be used when
no corresponding ``hw_machine_type`` image property is provided for the
instance.

When this option is not defined the libvirt driver relies on the following
`hardcoded dictionary`__ of default machine types per architecture:

.. __: https://github.com/openstack/nova/blob/dc93e3b510f53d5b2198c8edd22528f0c899617e/nova/virt/libvirt/utils.py#L631-L638

.. code-block:: python

    default_mtypes = {
        obj_fields.Architecture.ARMV7: "virt",
        obj_fields.Architecture.AARCH64: "virt",
        obj_fields.Architecture.S390: "s390-ccw-virtio",
        obj_fields.Architecture.S390X: "s390-ccw-virtio",
        obj_fields.Architecture.I686: "pc",
        obj_fields.Architecture.X86_64: "pc",
    }

Update
------

Prior to the Wallaby (23.0.0) release the
:oslo.config:option:`libvirt.hw_machine_type` option had to remain static once
set for the lifetime of a deployment. This was due to the machine type of
instances without a ``hw_machine_type`` image property using the newly
configured machine types after a hard reboot or migration This could in turn
break the internal ABI of the instance when changing between underlying machine
types such as ``pc`` to ``q35``.

From the Wallaby (23.0.0) release it is now possible to change the
:oslo.config:option:`libvirt.hw_machine_type` config once all instances have a
machine type recorded within the system metadata of the instance.

To allow this the libvirt driver will now attempt to record the machine type
for any instance that doesn't already have it recorded during start up of the
compute service or initial spawn of an instance. This should ensure a machine
type is recorded for all instances after an upgrade to Wallaby that are not in
a ``SHELVED_OFFLOADED`` state.

To record a machine type for instances in a ``SHELVED_OFFLOADED`` state after
an upgrade to Wallaby a new :program:`nova-manage` command has been introduced
to initially record the machine type of an instance.

.. code-block:: shell

    $ nova-manage libvirt update_machine_type $instance $machine_type

This command can also be used later to update the specific machine type used by
the instance. An additional :program:`nova-manage` command is also available to
fetch the machine type of a specific instance:

.. code-block:: shell

    $ nova-manage libvirt get_machine_type $instance

To confirm that all instances within an environment or a specific cell have had
a machine type recorded another :program:`nova-manage` command can be used:

.. code-block:: shell

    $ nova-manage libvirt list_unset_machine_type

The logic behind this command is also used by a new :program:`nova-status`
upgrade check that will fail with a warning when instances without a machine
type set exist in an environment.

.. code-block:: shell

    $ nova-status upgrade check

Once it has been verified that all instances within the environment or specific
cell have had a machine type recorded then the
:oslo.config:option:`libvirt.hw_machine_type` can be updated without impacting
existing instances.

Device bus and model image properties
-------------------------------------

.. versionadded:: 25.0.0 (Yoga)

Device bus and model types defined as image properties associated with an
instance are always used when launching instances with the libvirt driver.
Support for each device bus and model is dependent on the machine type used and
version of QEMU available on the underlying compute host. As such, any changes
to the machine type of an instance or version of QEMU on a host might suddenly
invalidate the stored device bus or model image properties.

It is now possible to change the stored image properties of an instance without
having to rebuild the instance.

To show the stored image properties of an instance:

.. code-block:: shell

    $ nova-manage image_property show $instance_uuid $property

To update the stored image properties of an instance:

.. code-block:: shell

    $ nova-manage image_property set \
        $instance_uuid --property $property_name=$property_value
