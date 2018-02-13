==================================
Recover from a failed compute node
==================================

If you deploy Compute with a shared file system, you can use several methods to
quickly recover from a node failure. This section discusses manual recovery.

.. _node-down-evacuate-instances:

Evacuate instances
~~~~~~~~~~~~~~~~~~

If a hardware malfunction or other error causes the cloud compute node to fail,
you can use the :command:`nova evacuate` command to evacuate instances.  See
:doc:`evacuate instances <evacuate>` for more information on using the command.

.. _nova-compute-node-down-manual-recovery:

Manual recovery
~~~~~~~~~~~~~~~

To manually recover a failed compute node:

#. Identify the VMs on the affected hosts by using a combination of the
   :command:`openstack server list` and :command:`openstack server show`
   commands.

#. Query the Compute database for the status of the host. This example converts
   an EC2 API instance ID to an OpenStack ID. If you use the :command:`nova`
   commands, you can substitute the ID directly. This example output is
   truncated:

   .. code-block:: none

      mysql> SELECT * FROM instances WHERE id = CONV('15b9', 16, 10) \G;
      *************************** 1. row ***************************
      created_at: 2012-06-19 00:48:11
      updated_at: 2012-07-03 00:35:11
      deleted_at: NULL
      ...
      id: 5561
      ...
      power_state: 5
      vm_state: shutoff
      ...
      hostname: at3-ui02
      host: np-rcc54
      ...
      uuid: 3f57699a-e773-4650-a443-b4b37eed5a06
      ...
      task_state: NULL
      ...

   .. note::

      Find the credentials for your database in ``/etc/nova.conf`` file.

#. Decide to which compute host to move the affected VM. Run this database
   command to move the VM to that host:

   .. code-block:: mysql

      mysql> UPDATE instances SET host = 'np-rcc46' WHERE uuid = '3f57699a-e773-4650-a443-b4b37eed5a06';

#. If you use a hypervisor that relies on libvirt, such as KVM, update the
   ``libvirt.xml`` file in ``/var/lib/nova/instances/[instance ID]`` with these
   changes:

   - Change the ``DHCPSERVER`` value to the host IP address of the new compute
     host.

   - Update the VNC IP to ``0.0.0.0``.

#. Reboot the VM:

   .. code-block:: console

      $ openstack server reboot 3f57699a-e773-4650-a443-b4b37eed5a06

Typically, the database update and :command:`openstack server reboot` command
recover a VM from a failed host. However, if problems persist, try one of these
actions:

- Use :command:`virsh` to recreate the network filter configuration.

- Restart Compute services.

- Update the ``vm_state`` and ``power_state`` fields in the Compute database.

Recover from a UID/GID mismatch
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Sometimes when you run Compute with a shared file system or an automated
configuration tool, files on your compute node might use the wrong UID or GID.
This UID or GID mismatch can prevent you from running live migrations or
starting virtual machines.

This procedure runs on ``nova-compute`` hosts, based on the KVM hypervisor:

#. Set the nova UID to the same number in ``/etc/passwd`` on all hosts. For
   example, set the UID to ``112``.

   .. note::

      Choose UIDs or GIDs that are not in use for other users or groups.

#. Set the ``libvirt-qemu`` UID to the same number in the ``/etc/passwd`` file
   on all hosts. For example, set the UID to ``119``.

#. Set the ``nova`` group to the same number in the ``/etc/group`` file on all
   hosts. For example, set the group to ``120``.

#. Set the ``libvirtd`` group to the same number in the ``/etc/group`` file on
   all hosts. For example, set the group to ``119``.

#. Stop the services on the compute node.

#. Change all files that the nova user or group owns. For example:

   .. code-block:: console

      # find / -uid 108 -exec chown nova {} \;
      # note the 108 here is the old nova UID before the change
      # find / -gid 120 -exec chgrp nova {} \;

#. Repeat all steps for the ``libvirt-qemu`` files, if required.

#. Restart the services.

#. To verify that all files use the correct IDs, run the :command:`find`
   command.

Recover cloud after disaster
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This section describes how to manage your cloud after a disaster and back up
persistent storage volumes. Backups are mandatory, even outside of disaster
scenarios.

For a definition of a disaster recovery plan (DRP), see
`https://en.wikipedia.org/wiki/Disaster\_Recovery\_Plan
<https://en.wikipedia.org/wiki/Disaster_Recovery_Plan>`_.

A disk crash, network loss, or power failure can affect several components in
your cloud architecture. The worst disaster for a cloud is a power loss. A
power loss affects these components:

- A cloud controller (``nova-api``, ``nova-objectstore``, ``nova-network``)

- A compute node (``nova-compute``)

- A storage area network (SAN) used by OpenStack Block Storage
  (``cinder-volumes``)

Before a power loss:

- Create an active iSCSI session from the SAN to the cloud controller (used
  for the ``cinder-volumes`` LVM's VG).

- Create an active iSCSI session from the cloud controller to the compute node
  (managed by ``cinder-volume``).

- Create an iSCSI session for every volume (so 14 EBS volumes requires 14
  iSCSI sessions).

- Create ``iptables`` or ``ebtables`` rules from the cloud controller to the
  compute node. This allows access from the cloud controller to the running
  instance.

- Save the current state of the database, the current state of the running
  instances, and the attached volumes (mount point, volume ID, volume status,
  etc), at least from the cloud controller to the compute node.

After power resumes and all hardware components restart:

- The iSCSI session from the SAN to the cloud no longer exists.

- The iSCSI session from the cloud controller to the compute node no longer
  exists.

- nova-network reapplies configurations on boot and, as a result, recreates
  the iptables and ebtables from the cloud controller to the compute node.

- Instances stop running.

  Instances are not lost because neither ``destroy`` nor ``terminate`` ran.
  The files for the instances remain on the compute node.

- The database does not update.

.. rubric:: Begin recovery

.. warning::

   Do not add any steps or change the order of steps in this procedure.

#. Check the current relationship between the volume and its instance, so that
   you can recreate the attachment.

   Use the :command:`openstack volume list` command to get this information.
   Note that the :command:`openstack` client can get volume information from
   OpenStack Block Storage.

#. Update the database to clean the stalled state. Do this for every volume by
   using these queries:

   .. code-block:: mysql

      mysql> use cinder;
      mysql> update volumes set mountpoint=NULL;
      mysql> update volumes set status="available" where status <>"error_deleting";
      mysql> update volumes set attach_status="detached";
      mysql> update volumes set instance_id=0;

   Use :command:`openstack volume list` command to list all volumes.

#. Restart the instances by using the :command:`openstack server reboot
   INSTANCE` command.

   .. important::

      Some instances completely reboot and become reachable, while some might
      stop at the plymouth stage. This is expected behavior. DO NOT reboot a
      second time.

      Instance state at this stage depends on whether you added an `/etc/fstab`
      entry for that volume. Images built with the cloud-init package remain in
      a ``pending`` state, while others skip the missing volume and start. You
      perform this step to ask Compute to reboot every instance so that the
      stored state is preserved. It does not matter if not all instances come
      up successfully. For more information about cloud-init, see
      `help.ubuntu.com/community/CloudInit/
      <https://help.ubuntu.com/community/CloudInit/>`__.

#. If required, run the :command:`openstack server add volume` command to
   reattach the volumes to their respective instances. This example uses a file
   of listed volumes to reattach them:

   .. code-block:: bash

      #!/bin/bash

      while read line; do
          volume=`echo $line | $CUT -f 1 -d " "`
          instance=`echo $line | $CUT -f 2 -d " "`
          mount_point=`echo $line | $CUT -f 3 -d " "`
              echo "ATTACHING VOLUME FOR INSTANCE - $instance"
          openstack server add volume $instance $volume $mount_point
          sleep 2
      done < $volumes_tmp_file

   Instances that were stopped at the plymouth stage now automatically continue
   booting and start normally. Instances that previously started successfully
   can now see the volume.

#. Log in to the instances with SSH and reboot them.

   If some services depend on the volume or if a volume has an entry in fstab,
   you can now restart the instance. Restart directly from the instance itself
   and not through :command:`nova`:

   .. code-block:: console

      # shutdown -r now

   When you plan for and complete a disaster recovery, follow these tips:

- Use the ``errors=remount`` option in the ``fstab`` file to prevent data
  corruption.

   In the event of an I/O error, this option prevents writes to the disk. Add
   this configuration option into the cinder-volume server that performs the
   iSCSI connection to the SAN and into the instances' ``fstab`` files.

- Do not add the entry for the SAN's disks to the cinder-volume's ``fstab``
  file.

   Some systems hang on that step, which means you could lose access to your
   cloud-controller. To re-run the session manually, run this command before
   performing the mount:

   .. code-block:: console

      # iscsiadm -m discovery -t st -p $SAN_IP $ iscsiadm -m node --target-name $IQN -p $SAN_IP -l

- On your instances, if you have the whole ``/home/`` directory on the disk,
  leave a user's directory with the user's bash files and the
  ``authorized_keys`` file instead of emptying the ``/home/`` directory and
  mapping the disk on it.

  This action enables you to connect to the instance without the volume
  attached, if you allow only connections through public keys.


To reproduce the power loss, connect to the compute node that runs that
instance and close the iSCSI session. Do not detach the volume by using the
:command:`openstack server remove volume` command. You must manually close the
iSCSI session. This example closes an iSCSI session with the number ``15``:

.. code-block:: console

   # iscsiadm -m session -u -r 15

Do not forget the ``-r`` option. Otherwise, all sessions close.

.. warning::

   There is potential for data loss while running instances during this
   procedure. If you are using Liberty or earlier, ensure you have the correct
   patch and set the options appropriately.
