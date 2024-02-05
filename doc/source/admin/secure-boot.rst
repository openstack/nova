===========
Secure Boot
===========

.. versionadded:: 14.0.0 (Newton)

.. versionchanged:: 23.0.0 (Wallaby)

    Added support for Secure Boot to the libvirt driver.

Nova supports configuring `UEFI Secure Boot`__ for guests. Secure Boot aims to
ensure no unsigned kernel code runs on a machine.

.. __: https://en.wikipedia.org/wiki/Secure_boot


Enabling Secure Boot
--------------------

Currently the configuration of UEFI guest bootloaders is only supported when
using the libvirt compute driver with a :oslo.config:option:`libvirt.virt_type`
of ``kvm`` or ``qemu``. In both cases, it requires the guests also be configured
with a :doc:`UEFI bootloader <uefi>`.

With these requirements satisfied, you can verify UEFI Secure Boot support by
inspecting the traits on the compute node's resource provider:

.. code:: bash

   $ COMPUTE_UUID=$(openstack resource provider list --name $HOST -f value -c uuid)
   $ openstack resource provider trait list $COMPUTE_UUID | grep COMPUTE_SECURITY_UEFI_SECURE_BOOT
   | COMPUTE_SECURITY_UEFI_SECURE_BOOT |


Configuring a flavor or image
-----------------------------

Configuring UEFI Secure Boot for guests varies depending on the compute driver
in use. In all cases, a :doc:`UEFI guest bootloader <uefi>` must be configured
for the guest but there are also additional requirements depending on the
compute driver in use.

.. rubric:: Libvirt

As the name would suggest, UEFI Secure Boot requires that a UEFI bootloader be
configured for guests. When this is done, UEFI Secure Boot support can be
configured using the :nova:extra-spec:`os:secure_boot` extra spec or equivalent
image metadata property. For example, to configure an image that meets both of
these requirements:

.. code-block:: bash

    $ openstack image set \
        --property hw_firmware_type=uefi \
        --property os_secure_boot=required \
        $IMAGE

.. note::

    On x86_64 hosts, enabling secure boot also requires configuring use of the
    Q35 machine type. This can be configured on a per-guest basis using the
    ``hw_machine_type`` image metadata property or automatically for all guests
    created on a host using the :oslo.config:option:`libvirt.hw_machine_type`
    config option.

It is also possible to explicitly request that secure boot be disabled. This is
the default behavior, so this request is typically useful when an admin wishes
to explicitly prevent a user requesting secure boot by uploading their own
image with relevant image properties. For example, to disable secure boot via
the flavor:

.. code-block:: bash

    $ openstack flavor set --property os:secure_boot=disabled $FLAVOR

Finally, it is possible to request that secure boot be enabled if the host
supports it. This is only possible via the image metadata property. When this
is requested, secure boot will only be enabled if the host supports this
feature and the other constraints, namely that a UEFI guest bootloader is
configured, are met. For example:

.. code-block:: bash

    $ openstack image set --property os_secure_boot=optional $IMAGE

.. note::

    If both the image metadata property and flavor extra spec are provided,
    they must match. If they do not, an error will be raised.

References
----------

* `Allow Secure Boot (SB) for QEMU- and KVM-based guests (spec)`__
* `Securing Secure Boot with System Management Mode`__

.. __: https://specs.openstack.org/openstack/nova-specs/specs/wallaby/approved/allow-secure-boot-for-qemu-kvm-guests.html
.. __: http://events17.linuxfoundation.org/sites/events/files/slides/kvmforum15-smm.pdf
