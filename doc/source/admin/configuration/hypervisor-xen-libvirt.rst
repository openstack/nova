===============
Xen via libvirt
===============

OpenStack Compute supports the Xen Project Hypervisor (or Xen). Xen can be
integrated with OpenStack Compute via the `libvirt <http://libvirt.org/>`_
`toolstack <http://wiki.xen.org/wiki/Choice_of_Toolstacks>`_ or via the `XAPI
<http://xenproject.org/developers/teams/xapi.html>`_ `toolstack
<http://wiki.xen.org/wiki/Choice_of_Toolstacks>`_.  This section describes how
to set up OpenStack Compute with Xen and libvirt.  For information on how to
set up Xen with XAPI refer to :doc:`hypervisor-xen-api`.

Installing Xen with libvirt
~~~~~~~~~~~~~~~~~~~~~~~~~~~

At this stage we recommend using the baseline that we use for the `Xen Project
OpenStack CI Loop
<http://wiki.xenproject.org/wiki/OpenStack_CI_Loop_for_Xen-Libvirt>`_, which
contains the most recent stability fixes to both Xen and libvirt.

`Xen 4.5.1
<https://xenproject.org/downloads/xen-project-archives/xen-project-4-5-series/xen-project-4-5-1/>`_
(or newer) and `libvirt 1.2.15 <http://libvirt.org/sources/>`_ (or newer)
contain the minimum required OpenStack improvements for Xen.  Although libvirt
1.2.15 works with Xen, libvirt 1.3.2 or newer is recommended.  The necessary
Xen changes have also been backported to the Xen 4.4.3 stable branch. Please
check with the Linux and FreeBSD distros you are intending to use as `Dom 0
<http://wiki.xenproject.org/wiki/Category:Host_Install>`_, whether the relevant
version of Xen and libvirt are available as installable packages.

The latest releases of Xen and libvirt packages that fulfil the above minimum
requirements for the various openSUSE distributions can always be found and
installed from the `Open Build Service
<https://build.opensuse.org/project/show/Virtualization>`_ Virtualization
project.  To install these latest packages, add the Virtualization repository
to your software management stack and get the newest packages from there.  More
information about the latest Xen and libvirt packages are available `here
<https://build.opensuse.org/package/show/Virtualization/xen>`__ and `here
<https://build.opensuse.org/package/show/Virtualization/libvirt>`__.

Alternatively, it is possible to use the Ubuntu LTS 14.04 Xen Package
**4.4.1-0ubuntu0.14.04.4** (Xen 4.4.1) and apply the patches outlined `here
<http://wiki.xenproject.org/wiki/OpenStack_CI_Loop_for_Xen-Libvirt#Baseline>`__.
You can also use the Ubuntu LTS 14.04 libvirt package **1.2.2
libvirt_1.2.2-0ubuntu13.1.7** as baseline and update it to libvirt version
1.2.15, or 1.2.14 with the patches outlined `here
<http://wiki.xenproject.org/wiki/OpenStack_CI_Loop_for_Xen-Libvirt#Baseline>`__
applied.  Note that this will require rebuilding these packages partly from
source.

For further information and latest developments, you may want to consult the
Xen Project's `mailing lists for OpenStack related issues and questions
<http://lists.xenproject.org/cgi-bin/mailman/listinfo/wg-openstack>`_.

Configuring Xen with libvirt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To enable Xen via libvirt, ensure the following options are set in
``/etc/nova/nova.conf`` on all hosts running the ``nova-compute`` service.

.. code-block:: ini

   compute_driver = libvirt.LibvirtDriver

   [libvirt]
   virt_type = xen

Additional configuration options
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the following as a guideline for configuring Xen for use in OpenStack:

#. **Dom0 memory**: Set it between 1GB and 4GB by adding the following
   parameter to the Xen Boot Options in the `grub.conf <http://
   xenbits.xen.org/docs/unstable/misc/xen-command-line.html>`_ file.

   .. code-block:: ini

      dom0_mem=1024M

   .. note::

      The above memory limits are suggestions and should be based on the
      available compute host resources. For large hosts that will run many
      hundreds of instances, the suggested values may need to be higher.

   .. note::

      The location of the grub.conf file depends on the host Linux distribution
      that you are using. Please refer to the distro documentation for more
      details (see `Dom 0 <http://wiki.xenproject.org
      /wiki/Category:Host_Install>`_ for more resources).

#. **Dom0 vcpus**: Set the virtual CPUs to 4 and employ CPU pinning by adding
   the following parameters to the Xen Boot Options in the `grub.conf
   <http://xenbits.xen.org/docs/unstable/misc/xen-command-line.html>`_ file.

   .. code-block:: ini

      dom0_max_vcpus=4 dom0_vcpus_pin

   .. note::

      Note that the above virtual CPU limits are suggestions and should be
      based on the available compute host resources. For large hosts, that will
      run many hundred of instances, the suggested values may need to be
      higher.

#. **PV vs HVM guests**: A Xen virtual machine can be paravirtualized (PV) or
   hardware virtualized (HVM). The virtualization mode determines the
   interaction between Xen, Dom 0, and the guest VM's kernel. PV guests are
   aware of the fact that they are virtualized and will co-operate with Xen and
   Dom 0. The choice of virtualization mode determines performance
   characteristics. For an overview of Xen virtualization modes, see `Xen Guest
   Types <http://wiki.xen.org/wiki/Xen_Overview#Guest_Types>`_.

   In OpenStack, customer VMs may run in either PV or HVM mode.  The mode is a
   property of the operating system image used by the VM, and is changed by
   adjusting the image metadata stored in the Image service.  The image
   metadata can be changed using the :command:`openstack` commands.

   To choose one of the HVM modes (HVM, HVM with PV Drivers or PVHVM), use
   :command:`openstack` to set the ``vm_mode`` property to ``hvm``.

   To choose one of the HVM modes (HVM, HVM with PV Drivers or PVHVM), use one
   of the following two commands:

   .. code-block:: console

      $ openstack image set --property vm_mode=hvm IMAGE

   To chose PV mode, which is supported by NetBSD, FreeBSD and Linux, use one
   of the following two commands

   .. code-block:: console

      $ openstack image set --property vm_mode=xen IMAGE

   .. note::

      The default for virtualization mode in nova is PV mode.

#. **Image formats**: Xen supports raw, qcow2 and vhd image formats.  For more
   information on image formats, refer to the `OpenStack Virtual Image Guide
   <https://docs.openstack.org/image-guide/introduction.html>`__ and the
   `Storage Options Guide on the Xen Project Wiki
   <http://wiki.xenproject.org/wiki/Storage_options>`_.

#. **Image metadata**: In addition to the ``vm_mode`` property discussed above,
   the ``hypervisor_type`` property is another important component of the image
   metadata, especially if your cloud contains mixed hypervisor compute nodes.
   Setting the ``hypervisor_type`` property allows the nova scheduler to select
   a compute node running the specified hypervisor when launching instances of
   the image. Image metadata such as ``vm_mode``, ``hypervisor_type``,
   architecture, and others can be set when importing the image to the Image
   service. The metadata can also be changed using the :command:`openstack`
   commands:

   .. code-block:: console

      $ openstack image set --property hypervisor_type=xen vm_mode=hvm IMAGE

   For more information on image metadata, refer to the `OpenStack Virtual
   Image Guide <https://docs.openstack.org/image-guide/image-metadata.html>`__.

#. **Libguestfs file injection**: OpenStack compute nodes can use `libguestfs
   <http://libguestfs.org/>`_ to inject files into an instance's image prior to
   launching the instance. libguestfs uses libvirt's QEMU driver to start a
   qemu process, which is then used to inject files into the image. When using
   libguestfs for file injection, the compute node must have the libvirt qemu
   driver installed, in addition to the Xen driver. In RPM based distributions,
   the qemu driver is provided by the ``libvirt-daemon-qemu`` package. In
   Debian and Ubuntu, the qemu driver is provided by the ``libvirt-bin``
   package.

Troubleshoot Xen with libvirt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Important log files**: When an instance fails to start, or when you come
across other issues, you should first consult the following log files:

* ``/var/log/nova/nova-compute.log``

* ``/var/log/libvirt/libxl/libxl-driver.log``,

* ``/var/log/xen/qemu-dm-${instancename}.log``,

* ``/var/log/xen/xen-hotplug.log``,

* ``/var/log/xen/console/guest-${instancename}`` (to enable see `Enabling Guest
  Console Logs
  <http://wiki.xen.org/wiki/Reporting_Bugs_against_Xen#Guest_console_logs>`_)

* Host Console Logs (read `Enabling and Retrieving Host Console Logs
  <http://wiki.xen.org/wiki/Reporting_Bugs_against_Xen#Host_console_logs>`_).

If you need further help you can ask questions on the mailing lists `xen-users@
<http://lists.xenproject.org/cgi-bin/mailman/listinfo/ xen-users>`_,
`wg-openstack@ <http://lists.xenproject.org/cgi-bin/mailman/
listinfo/wg-openstack>`_ or `raise a bug <http://wiki.xen.org/wiki/
Reporting_Bugs_against_Xen>`_ against Xen.

Known issues
~~~~~~~~~~~~

* **Live migration**: Live migration is supported in the libvirt libxl driver
  since version 1.2.5. However, there were a number of issues when used with
  OpenStack, in particular with libvirt migration protocol compatibility. It is
  worth mentioning that libvirt 1.3.0 addresses most of these issues.  We do
  however recommend using libvirt 1.3.2, which is fully supported and tested as
  part of the Xen Project CI loop. It addresses live migration monitoring
  related issues and adds support for peer-to-peer migration mode, which nova
  relies on.

* **Live migration monitoring**: On compute nodes running Kilo or later, live
  migration monitoring relies on libvirt APIs that are only implemented from
  libvirt version 1.3.1 onwards. When attempting to live migrate, the migration
  monitoring thread would crash and leave the instance state as "MIGRATING". If
  you experience such an issue and you are running on a version released before
  libvirt 1.3.1, make sure you backport libvirt commits ad71665 and b7b4391
  from upstream.

Additional information and resources
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The following section contains links to other useful resources.

* `wiki.xenproject.org/wiki/OpenStack <http://wiki.xenproject.org/wiki/
  OpenStack>`_ - OpenStack Documentation on the Xen Project wiki

* `wiki.xenproject.org/wiki/OpenStack_CI_Loop_for_Xen-Libvirt
  <http://wiki.xenproject.org/wiki/OpenStack_CI_Loop_for_Xen-Libvirt>`_ -
  Information about the Xen Project OpenStack CI Loop

* `wiki.xenproject.org/wiki/OpenStack_via_DevStack
  <http://wiki.xenproject.org/wiki/OpenStack_via_DevStack>`_ - How to set up
  OpenStack via DevStack

* `Mailing lists for OpenStack related issues and questions
  <http://lists.xenproject.org/cgi-bin/mailman/listinfo/wg-openstack>`_ - This
  list is dedicated to coordinating bug fixes and issues across Xen, libvirt
  and OpenStack and the CI loop.
