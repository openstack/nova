==========================
Boot an instance using PXE
==========================

Follow the steps below to boot an existing instance using PXE.

Create an image with iPXE
=========================

iPXE is open source boot firmware. See the documentation for more details:
https://ipxe.org/docs

Use the iPXE image as a rescue image
====================================

Boot the instance from the iPXE image using rescue.

Legacy instance rescue
----------------------

The ordering of disks is not guaranteed to be consistent.

.. code-block:: console

   $ openstack server rescue --image IPXE_IMAGE INSTANCE_NAME

Stable device instance rescue
-----------------------------

To preserve the ordering of disks when booting, use `stable device rescue`_.

#. Ensure that the ``hw_rescue_device`` (``cdrom`` | ``disk`` | ``floppy``)
   and/or the ``hw_rescue_bus`` (``scsi`` | ``virtio`` | ``ide`` | ``usb``) image
   properties are set on the image. For example:

   .. code-block:: console

      $ openstack image set --property hw_rescue_device=disk IPXE_IMAGE

   or:

   .. code-block:: console

      $ openstack image set --property hw_rescue_bus=virtio IPXE_IMAGE

   or:

   .. code-block:: console

      $ openstack image set --property hw_rescue_device=disk \
        --property hw_rescue_bus=virtio IPXE_IMAGE

#. Run the rescue using the API microversion 2.87 or later:

   .. code-block:: console

      $ openstack --os-compute-api-version 2.87 server rescue \
        --image IPXE_IMAGE INSTANCE_NAME


.. _stable device rescue: https://docs.openstack.org/nova/latest/user/rescue.html#stable-device-instance-rescue
