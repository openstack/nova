zVM
===

z/VM System Requirements
~~~~~~~~~~~~~~~~~~~~~~~~

* The appropriate APARs installed, the current list of which can be found: z/VM
  OpenStack Cloud Information (http://www.vm.ibm.com/sysman/osmntlvl.html).

.. note::

  IBM z Systems hardware requirements are based on both the applications and
  the load on the system.

Active Engine Guide
~~~~~~~~~~~~~~~~~~~

Active engine is used as an initial configuration and management tool during
deployed machine startup. Currently the z/VM driver uses ``zvmguestconfigure``
and ``cloud-init`` as a two stage active engine.

Installation and Configuration of zvmguestconfigure
---------------------------------------------------

Cloudlib4zvm supports initiating changes to a Linux on z Systems virtual
machine while Linux is shut down or the virtual machine is logged off.
The changes to Linux are implemented using an activation engine (AE)
that is run when Linux is booted the next time. The first active engine,
``zvmguestconfigure``, must be installed in the Linux on z Systems virtual
server so it can process change request files transmitted by the
cloudlib4zvm service to the reader of the virtual machine as a class X file.

.. note::

   An additional activation engine, cloud-init, should be installed to handle
   OpenStack related tailoring of the system.
   The cloud-init AE relies on tailoring performed by ``zvmguestconfigure``.

Installation and Configuration of cloud-init
--------------------------------------------

OpenStack uses cloud-init as its activation engine. Some Linux distributions
include cloud-init either already installed or available to be installed.
If your distribution does not include cloud-init, you can download
the code from https://launchpad.net/cloud-init/+download.
After installation, if you issue the following
shell command and no errors occur, cloud-init is installed correctly::

    cloud-init init --local

Installation and configuration of cloud-init differs among different Linux
distributions, and cloud-init source code may change. This section provides
general information, but you may have to tailor cloud-init
to meet the needs of your Linux distribution. You can find a
community-maintained list of dependencies at http://ibm.biz/cloudinitLoZ.

As of the Rocky release, the z/VM OpenStack support has been tested with
cloud-init 0.7.4 and 0.7.5 for RHEL6.x and SLES11.x, 0.7.6 for RHEL7.x and
SLES12.x, and 0.7.8 for Ubuntu 16.04.

During cloud-init installation, some dependency packages may be required.
You can use zypper and python setuptools to easily resolve these dependencies.
See https://pypi.python.org/pypi/setuptools for more information.

Image guide
~~~~~~~~~~~

This guideline will describe the requirements and steps to create and
configure images for use with z/VM.

Image Requirements
------------------

* The following Linux distributions are supported for deploy:

  * RHEL 6.2, 6.3, 6.4, 6.5, 6.6, and 6.7
  * RHEL 7.0, 7.1 and 7.2
  * SLES 11.2, 11.3, and 11.4
  * SLES 12 and SLES 12.1
  * Ubuntu 16.04

* A supported root disk type for snapshot/spawn. The following are supported:

  * FBA
  * ECKD

* An image deployed on a compute node must match the disk type supported by
  that compute node, as configured by the ``zvm_diskpool_type`` property in
  the `zvmsdk.conf`_ configuration file in `zvm cloud connector`_
  A compute node supports deployment on either an ECKD or FBA image,
  but not both at the same time. If you wish to switch image types,
  you need to change the ``zvm_diskpool_type`` and
  ``zvm_diskpool`` properties in the `zvmsdk.conf`_ file, accordingly.
  Then restart the nova-compute service to make the changes take effect.

* If you deploy an instance with an ephemeral disk, both the root disk and the
  ephemeral disk will be created with the disk type that was specified by
  ``zvm_diskpool_type`` property in the `zvmsdk.conf`_ file. That property can
  specify either ECKD or FBA.

* The network interfaces must be IPv4 interfaces.

* Image names should be restricted to the UTF-8 subset, which corresponds to
  the ASCII character set. In addition, special characters such as ``/``, ``\``,
  ``$``, ``%``, ``@`` should not be used. For the FBA disk type "vm",
  capture and deploy is supported only for an FBA disk with a single partition.
  Capture and deploy is not supported for the FBA disk type "vm" on a CMS
  formatted FBA disk.

* The virtual server/Linux instance used as the source of the new image should
  meet the following criteria:

  1. The root filesystem must not be on a logical volume.

  2. The minidisk on which the root filesystem resides should be a minidisk of
     the same type as desired for a subsequent deploy (for example, an ECKD disk
     image should be captured for a subsequent deploy to an ECKD disk).

  3. The minidisks should not be a full-pack minidisk, since cylinder 0 on
     full-pack minidisks is reserved, and should be defined with virtual
     address 0100.

  4. The root disk should have a single partition.

  5. The image being captured should not have any network interface cards (NICs)
     defined below virtual address 1100.

In addition to the specified criteria, the following recommendations allow for
efficient use of the image:

* The minidisk on which the root filesystem resides should be defined as a
  multiple of full gigabytes in size (for example, 1GB or 2GB).
  OpenStack specifies disk sizes in full gigabyte values, whereas z/VM
  handles disk sizes in other ways (cylinders for ECKD disks, blocks for FBA
  disks, and so on). See the appropriate online information if you need to
  convert cylinders or blocks to gigabytes; for example:
  http://www.mvsforums.com/helpboards/viewtopic.php?t=8316.

* During subsequent deploys of the image, the OpenStack code will ensure that
  a disk image is not copied to a disk smaller than the source disk,
  as this would result in loss of data. The disk specified in
  the flavor should therefore be equal to or slightly larger than the source
  virtual machine's root disk.

.. _zvmsdk.conf: https://cloudlib4zvm.readthedocs.io/en/latest/configuration.html#configuration-options
.. _zvm cloud connector: https://cloudlib4zvm.readthedocs.io/en/latest/
