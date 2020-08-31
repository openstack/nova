=============
Config drives
=============

.. note::

   This section provides deployment information about the config drive feature.
   For end-user information about the config drive feature and instance metadata
   in general, refer to the :doc:`user guide </user/metadata>`.

Config drives are special drives that are attached to an instance when it boots.
The instance can mount this drive and read files from it to get information that
is normally available through :doc:`the metadata service
</admin/metadata-service>`.

There are many use cases for the config drive. One such use case is to pass a
networking configuration when you do not use DHCP to assign IP addresses to
instances. For example, you might pass the IP address configuration for the
instance through the config drive, which the instance can mount and access
before you configure the network settings for the instance. Another common
reason to use config drives is load. If running something like the OpenStack
puppet providers in your instances, they can hit the :doc:`metadata servers
</admin/metadata-service>` every fifteen minutes, simultaneously for every
instance you have. They are just checking in, and building facts, but it's not
insignificant load. With a config drive, that becomes a local (cached) disk
read. Finally, using a config drive means you're not dependent on the metadata
service being up, reachable, or performing well to do things like reboot your
instance that runs `cloud-init`_ at the beginning.

Any modern guest operating system that is capable of mounting an ISO 9660 or
VFAT file system can use the config drive.


Requirements and guidelines
---------------------------

To use the config drive, you must follow the following requirements for the
compute host and image.

.. rubric:: Compute host requirements

The following virt drivers support the config drive: libvirt,
Hyper-V, VMware, and (since 17.0.0 Queens) PowerVM. The Bare Metal service also
supports the config drive.

- To use config drives with libvirt or VMware, you must first
  install the :command:`genisoimage` package on each compute host. Use the
  :oslo.config:option:`mkisofs_cmd` config option to set the path where you
  install the :command:`genisoimage` program. If :command:`genisoimage` is in
  the same path as the :program:`nova-compute` service, you do not need to set
  this flag.

- To use config drives with Hyper-V, you must set the
  :oslo.config:option:`mkisofs_cmd` config option to the full path to an
  :command:`mkisofs.exe` installation. Additionally, you must set the
  :oslo.config:option:`hyperv.qemu_img_cmd` config option to the full path to an
  :command:`qemu-img` command installation.

- To use config drives with PowerVM or the Bare Metal service, you do not need
  to prepare anything.

.. rubric:: Image requirements

An image built with a recent version of the `cloud-init`_ package can
automatically access metadata passed through the config drive. The cloud-init
package version 0.7.1 works with Ubuntu, Fedora based images (such as Red Hat
Enterprise Linux) and openSUSE based images (such as SUSE Linux Enterprise
Server). If an image does not have the cloud-init package installed, you must
customize the image to run a script that mounts the config drive on boot, reads
the data from the drive, and takes appropriate action such as adding the public
key to an account.  For more details about how data is organized on the config
drive, refer to the :ref:`user guide <metadata-config-drive>`.


Configuration
-------------

The :program:`nova-compute` service accepts the following config drive-related
options:

- :oslo.config:option:`api.config_drive_skip_versions`
- :oslo.config:option:`force_config_drive`
- :oslo.config:option:`config_drive_format`

If using the HyperV compute driver, the following additional options are
supported:

- :oslo.config:option:`hyperv.config_drive_cdrom`

For example, to ensure nova always provides a config drive to instances but
versions ``2018-08-27`` (Rocky) and ``2017-02-22`` (Ocata) are skipped, add the
following to :file:`nova.conf`:

.. code-block:: ini

    [DEFAULT]
    force_config_drive = True

    [api]
    config_drive_skip_versions = 2018-08-27 2017-02-22

.. note::

    The ``img_config_drive`` image metadata property can be used to force enable
    the config drive. In addition, users can explicitly request a config drive
    when booting instances. For more information, refer to the :ref:`user guide
    <metadata-config-drive>`.

.. _cloud-init: https://cloudinit.readthedocs.io/en/latest/
