.. _section_configuring-compute-migrations:

=========================
Configure live migrations
=========================

Migration enables an administrator to move a virtual machine instance from one
compute host to another. A typical scenario is planned maintenance on the
source host, but migration can also be useful to redistribute the load when
many VM instances are running on a specific physical machine.

This document covers live migrations using the
:ref:`configuring-migrations-kvm-libvirt` and VMWare hypervisors

.. :ref:`_configuring-migrations-kvm-libvirt`

.. note::

   Not all Compute service hypervisor drivers support live-migration, or
   support all live-migration features. Similarly not all compute service
   features are supported.

   Consult :doc:`/user/support-matrix` to determine which hypervisors
   support live-migration.

   See the :doc:`/configuration/index` for details
   on hypervisor configuration settings.

The migration types are:

- **Non-live migration**, also known as cold migration or simply migration.

  The instance is shut down, then moved to another hypervisor and restarted.
  The instance recognizes that it was rebooted, and the application running on
  the instance is disrupted.

  This section does not cover cold migration.

- **Live migration**

  The instance keeps running throughout the migration.  This is useful when it
  is not possible or desirable to stop the application running on the instance.

  Live migrations can be classified further by the way they treat instance
  storage:

  - **Shared storage-based live migration**. The instance has ephemeral disks
    that are located on storage shared between the source and destination
    hosts.

  - **Block live migration**, or simply block migration.  The instance has
    ephemeral disks that are not shared between the source and destination
    hosts.  Block migration is incompatible with read-only devices such as
    CD-ROMs and Configuration Drive (config\_drive).

  - **Volume-backed live migration**. Instances use volumes rather than
    ephemeral disks.

  Block live migration requires copying disks from the source to the
  destination host. It takes more time and puts more load on the network.
  Shared-storage and volume-backed live migration does not copy disks.

.. note::

   In a multi-cell cloud, instances can be live migrated to a
   different host in the same cell, but not across cells.

The following sections describe how to configure your hosts for live migrations
using the libvirt virt driver and KVM hypervisor.

.. _configuring-migrations-kvm-libvirt:

Libvirt
-------

.. _configuring-migrations-kvm-general:

General configuration
~~~~~~~~~~~~~~~~~~~~~

To enable any type of live migration, configure the compute hosts according to
the instructions below:

#. Set the following parameters in ``nova.conf`` on all compute hosts:

   - ``server_listen=0.0.0.0``

     You must not make the VNC server listen to the IP address of its compute
     host, since that addresses changes when the instance is migrated.

     .. important::

        Since this setting allows VNC clients from any IP address to connect to
        instance consoles, you must take additional measures like secure
        networks or firewalls to prevent potential attackers from gaining
        access to instances.

   - ``instances_path`` must have the same value for all compute hosts. In
     this guide, the value ``/var/lib/nova/instances`` is assumed.

#. Ensure that name resolution on all compute hosts is identical, so that they
   can connect each other through their hostnames.

   If you use ``/etc/hosts`` for name resolution and enable SELinux, ensure
   that ``/etc/hosts`` has the correct SELinux context:

   .. code-block:: console

      # restorecon /etc/hosts

#. Enable password-less SSH so that root on one compute host can log on to any
   other compute host without providing a password.  The ``libvirtd`` daemon,
   which runs as root, uses the SSH protocol to copy the instance to the
   destination and can't know the passwords of all compute hosts.

   You may, for example, compile root's public SSH keys on all compute hosts
   into an ``authorized_keys`` file and deploy that file to the compute hosts.

#. Configure the firewalls to allow libvirt to communicate between compute
   hosts.

   By default, libvirt uses the TCP port range from 49152 to 49261 for copying
   memory and disk contents. Compute hosts must accept connections in this
   range.

   For information about ports used by libvirt, see the `libvirt documentation
   <http://libvirt.org/remote.html#Remote_libvirtd_configuration>`_.

   .. important::

      Be mindful of the security risks introduced by opening ports.

.. _`configuring-migrations-securing-live-migration-streams`:

Securing live migration streams
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your compute nodes have at least libvirt 4.4.0 and QEMU 2.11.0, it is
strongly recommended to secure all your live migration streams by taking
advantage of the "QEMU-native TLS" feature.  This requires a
pre-existing PKI (Public Key Infrastructure) setup.  For further details
on how to set this all up, refer to the
:doc:`secure-live-migration-with-qemu-native-tls` document.


.. _configuring-migrations-kvm-block-and-volume-migration:

Block migration, volume-based live migration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If your environment satisfies the requirements for "QEMU-native TLS",
then block migration requires some setup; refer to the above section,
`Securing live migration streams`_, for details.  Otherwise, no
additional configuration is required for block migration and
volume-backed live migration.

Be aware that block migration adds load to the network and storage subsystems.

.. _configuring-migrations-kvm-shared-storage:

Shared storage
~~~~~~~~~~~~~~

Compute hosts have many options for sharing storage, for example NFS, shared
disk array LUNs, Ceph or GlusterFS.

The next steps show how a regular Linux system might be configured as an NFS v4
server for live migration.  For detailed information and alternative ways to
configure NFS on Linux, see instructions for `Ubuntu`_, `RHEL and derivatives`_
or `SLES and OpenSUSE`_.

.. _`Ubuntu`: https://help.ubuntu.com/community/SettingUpNFSHowTo
.. _`RHEL and derivatives`: https://access.redhat.com/documentation/en-US/Red_Hat_Enterprise_Linux/7/html/Storage_Administration_Guide/nfs-serverconfig.html
.. _`SLES and OpenSUSE`: https://www.suse.com/documentation/sles-12/book_sle_admin/data/sec_nfs_configuring-nfs-server.html

#. Ensure that UID and GID of the nova user are identical on the compute hosts
   and the NFS server.

#. Create a directory with enough disk space for all instances in the cloud,
   owned by user nova. In this guide, we assume ``/var/lib/nova/instances``.

#. Set the execute/search bit on the ``instances`` directory:

   .. code-block:: console

      $ chmod o+x /var/lib/nova/instances

   This  allows qemu to access the ``instances`` directory tree.

#. Export ``/var/lib/nova/instances`` to the compute hosts. For example, add
   the following line to ``/etc/exports``:

   .. code-block:: ini

      /var/lib/nova/instances *(rw,sync,fsid=0,no_root_squash)

   The asterisk permits access to any NFS client. The option ``fsid=0`` exports
   the instances directory as the NFS root.

After setting up the NFS server, mount the remote filesystem on all compute
hosts.

#. Assuming the NFS server's hostname is ``nfs-server``, add this line to
   ``/etc/fstab`` to mount the NFS root:

   .. code-block:: console

      nfs-server:/ /var/lib/nova/instances nfs4 defaults 0 0

#. Test NFS by mounting the instances directory and check access permissions
   for the nova user:

   .. code-block:: console

      $ sudo mount -a -v
      $ ls -ld /var/lib/nova/instances/
      drwxr-xr-x. 2 nova nova 6 Mar 14 21:30 /var/lib/nova/instances/

.. _configuring-migrations-kvm-advanced:

Advanced configuration for KVM and QEMU
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Live migration copies the instance's memory from the source to the destination
compute host. After a memory page has been copied, the instance may write to it
again, so that it has to be copied again.  Instances that frequently write to
different memory pages can overwhelm the memory copy process and prevent the
live migration from completing.

This section covers configuration settings that can help live migration of
memory-intensive instances succeed.

#. **Live migration completion timeout**

   The Compute service will either abort or force complete a migration
   when it has been running too long. This behavior is configurable
   using the :oslo.config:option:`libvirt.live_migration_timeout_action`
   config option. The timeout is calculated based on the instance size, which
   is the instance's memory size in GiB. In the case of block migration, the
   size of ephemeral storage in GiB is added.

   The timeout in seconds is the instance size multiplied by the configurable
   parameter :oslo.config:option:`libvirt.live_migration_completion_timeout`,
   whose default is 800. For example, shared-storage live migration of an
   instance with 8GiB memory will time out after 6400 seconds.

#. **Instance downtime**

   Near the end of the memory copy, the instance is paused for a short time so
   that the remaining few pages can be copied without interference from
   instance memory writes. The Compute service initializes this time to a small
   value that depends on the instance size, typically around 50 milliseconds.
   When it notices that the memory copy does not make sufficient progress, it
   increases the time gradually.

   You can influence the instance downtime algorithm with the help of three
   configuration variables on the compute hosts:

   .. code-block:: ini

      live_migration_downtime = 500
      live_migration_downtime_steps = 10
      live_migration_downtime_delay = 75

   ``live_migration_downtime`` sets the maximum permitted downtime for a live
   migration, in *milliseconds*.  The default is 500.

   ``live_migration_downtime_steps`` sets the total number of adjustment steps
   until ``live_migration_downtime`` is reached.  The default is 10 steps.

   ``live_migration_downtime_delay`` sets the time interval between two
   adjustment steps in *seconds*. The default is 75.

#. **Auto-convergence**

   One strategy for a successful live migration of a memory-intensive instance
   is slowing the instance down. This is called auto-convergence.  Both libvirt
   and QEMU implement this feature by automatically throttling the instance's
   CPU when memory copy delays are detected.

   Auto-convergence is disabled by default.  You can enable it by setting
   ``live_migration_permit_auto_converge=true``.

   .. caution::

      Before enabling auto-convergence, make sure that the instance's
      application tolerates a slow-down.

      Be aware that auto-convergence does not guarantee live migration success.

#. **Post-copy**

   Live migration of a memory-intensive instance is certain to succeed when you
   enable post-copy. This feature, implemented by libvirt and QEMU, activates
   the virtual machine on the destination host before all of its memory has
   been copied.  When the virtual machine accesses a page that is missing on
   the destination host, the resulting page fault is resolved by copying the
   page from the source host.

   Post-copy is disabled by default. You can enable it by setting
   ``live_migration_permit_post_copy=true``.

   When you enable both auto-convergence and post-copy, auto-convergence
   remains disabled.

   .. caution::

      The page faults introduced by post-copy can slow the instance down.

      When the network connection between source and destination host is
      interrupted, page faults cannot be resolved anymore and the instance is
      rebooted.

.. TODO Bernd: I *believe* that it is certain to succeed,
.. but perhaps I am missing something.

The full list of live migration configuration parameters is documented in the
:doc:`Nova Configuration Options </configuration/config>`


VMware
------

.. :ref:`_configuring-migrations-vmware`

.. _configuring-migrations-vmware:

vSphere configuration
~~~~~~~~~~~~~~~~~~~~~

Enable vMotion on all ESX hosts which are managed by Nova by following the
instructions in `this <https://kb.vmware.com/s/article/2054994>`_ KB article.
