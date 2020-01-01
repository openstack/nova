==================
Rescue an instance
==================

Instance rescue provides a mechanism for access, even if an image renders the
instance inaccessible. Two rescue modes are currently provided.

Instance rescue
---------------

By default the instance is booted from the provided rescue image or a fresh
copy of the original instance image if a rescue image is not provided. The root
disk and optional regenerated config drive are also attached to the instance
for data recovery.

.. note::

   Rescuing a volume-backed instance is not supported with this mode.

Stable device instance rescue
-----------------------------

As of 21.0.0 (Ussuri) an additional stable device rescue mode is available.
This mode now supports the rescue of volume-backed instances.

This mode keeps all devices both local and remote attached in their original
order to the instance during the rescue while booting from the provided rescue
image. This mode is enabled and controlled by the presence of
``hw_rescue_device`` or ``hw_rescue_bus`` image properties on the provided
rescue image.

As their names suggest these properties control the rescue device type
(``cdrom``, ``disk`` or ``floppy``) and bus type (``scsi``, ``virtio``,
``ide``, or ``usb``) used when attaching the rescue image to the instance.

Support for each combination of the ``hw_rescue_device`` and ``hw_rescue_bus``
image properties is dependent on the underlying hypervisor and platform being
used. For example the ``IDE`` bus is not available on POWER KVM based compute
hosts.

.. note::

   This mode is only supported when using the Libvirt virt driver.

   This mode is not supported when using LXC or Xen hypervisors as enabled by
   the :oslo.config:option:`libvirt.virt_type` configurable on the computes.

Usage
-----

.. note::

   Pause, suspend, and stop operations are not allowed when an instance
   is running in rescue mode, as triggering these actions causes the
   loss of the original instance state and makes it impossible to
   unrescue the instance.

To perform an instance rescue, use the :command:`openstack server rescue`
command:

.. code-block:: console

   $ openstack server rescue SERVER

.. note::

   On running the :command:`openstack server rescue` command,
   an instance performs a soft shutdown first. This means that
   the guest operating system has a chance to perform
   a controlled shutdown before the instance is powered off.
   The shutdown behavior is configured by the
   :oslo.config:option:`shutdown_timeout` parameter that can be set in the
   ``nova.conf`` file.
   Its value stands for the overall period (in seconds)
   a guest operating system is allowed to complete the shutdown.

   The timeout value can be overridden on a per image basis
   by means of ``os_shutdown_timeout`` that is an image metadata
   setting allowing different types of operating systems to specify
   how much time they need to shut down cleanly.

If you want to rescue an instance with a specific image, rather than the
default one, use the ``--image`` parameter:

.. code-block:: console

   $ openstack server rescue --image IMAGE_ID SERVER

To restart the instance from the normal boot disk, run the following
command:

.. code-block:: console

   $ openstack server unrescue SERVER
