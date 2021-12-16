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

============================================================================
hw_emulation_architecture - Configuring QEMU instance emulation architecture
============================================================================

.. versionadded:: 25.0.0 (Yoga)

   The libvirt driver now allows for handling of specific cpu architectures
   when defined within the image metadata properties, to be emulated through
   QEMU.

   Added ``hw_emulation_architecture`` as an available image_meta property.

.. note::

   The following only applies to environments using libvirt compute hosts.
   and should be considered experimental in its entirety, during its first
   release as a feature.

Introduction
------------

This capability is to fill a need with environments that do not have the
capability to support the various cpu architectures that are present today
with physical hardware. A small subset of architectures that are supported
both within libvirt and QEMU have been selected as prime candidates for
emulation support.

While support has been added for the below base architectures, this does
not guarantee that every subset or custom operating system that leverages
one of these architectures will function.

Configure
---------

-------------------
QEMU Binary Support
-------------------

To ensure that libvirt and QEMU can properly handle the level of cpu
emulation desired by the end-user, you are required to install the specific
``qemu-system-XXX``, ``qemu-efi-arm``, ``qemu-efi-aarch64`` binaries on the
compute nodes that will be providing support.

---------------
Console Support
---------------

Consideration need to be made in regards to which architectures you want to
support, as there are limitations on support through spice, novnc, and
serial. All testing and validation has been done to ensure that spice and
serial connections function as expected.

- ``AARCH64`` - Spice & Serial
- ``S390X`` - Serial
- ``PPC64LE`` - Spice & Serial
- ``MIPSEL`` - untested

--------------------------------
Supported Emulated Architectures
--------------------------------

The supported emulated architectures require specific image meta
properties to be set in order to trigger the proper settings to be
configured by libvirtd.

For end users the emulation architecture of an instance is controlled by the
selection of an image with the ``hw_emulation_architecture`` image metadata
property set.


AARCH64
~~~~~~~

``Tested and Validated as functional``

.. code-block:: shell

    $ openstack image set --property hw_emulation_architecture=aarch64 $IMAGE
    $ openstack image set --property hw_machine_type=virt $IMAGE
    $ openstack image set --property hw_firmware_type=uefi $IMAGE

S390x
~~~~~

``Tested and Validated as functional``

.. code-block:: shell

    $ openstack image set --property hw_emulation_architecture=s390x $IMAGE
    $ openstack image set --property hw_machine_type=s390-ccw-virtio $IMAGE
    $ openstack image set --property hw_video_model=virtio $IMAGE

PPC64LE
~~~~~~~

``Tested and Validated as functional``

.. code-block:: shell

    $ openstack image set --property hw_emulation_architecture=ppc64le $IMAGE
    $ openstack image set --property hw_machine_type=pseries $IMAGE


MIPSEL
~~~~~~

``Testing and validation is ongoing to overcome PCI issues``

.. note::

   Support is currently impacted, one current method for support is manually
   patching and compiling as defined in libvirt bug
   `XML error: No PCI buses available`_.

.. _`XML error: No PCI buses available`: https://bugzilla.redhat.com/show_bug.cgi?id=1432101

.. code-block:: shell

    $ openstack image set --property hw_emulation_architecture=mipsel $IMAGE
    $ openstack image set --property hw_machine_type=virt $IMAGE
