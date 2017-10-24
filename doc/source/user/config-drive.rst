=======================================
Store metadata on a configuration drive
=======================================
You can configure OpenStack to write metadata to a special configuration drive
that attaches to the instance when it boots. The instance can mount this drive
and read files from it to get information that is normally available through
the :ref:`metadata service <metadata-service>`.
This metadata is different from the user data.

One use case for using the configuration drive is to pass a networking
configuration when you do not use DHCP to assign IP addresses to
instances. For example, you might pass the IP address configuration for
the instance through the configuration drive, which the instance can
mount and access before you configure the network settings for the
instance.

Any modern guest operating system that is capable of mounting an ISO
9660 or VFAT file system can use the configuration drive.

Requirements and guidelines
~~~~~~~~~~~~~~~~~~~~~~~~~~~

To use the configuration drive, you must follow the following
requirements for the compute host and image.

**Compute host requirements**

-  The following hypervisors support the configuration drive: libvirt,
   XenServer, Hyper-V, and VMware.

   Also, the Bare Metal service supports the configuration drive.

-  To use configuration drive with libvirt, XenServer, or VMware, you
   must first install the genisoimage package on each compute host.
   Otherwise, instances do not boot properly.

   Use the ``mkisofs_cmd`` flag to set the path where you install the
   genisoimage program. If genisoimage is in same path as the
   ``nova-compute`` service, you do not need to set this flag.

-  To use configuration drive with Hyper-V, you must set the
   ``mkisofs_cmd`` value to the full path to an ``mkisofs.exe``
   installation. Additionally, you must set the ``qemu_img_cmd`` value
   in the ``hyperv`` configuration section to the full path to an
   :command:`qemu-img` command installation.

-  To use configuration drive with the Bare Metal service,
   you do not need to prepare anything because the Bare Metal
   service treats the configuration drive properly.

**Image requirements**

-  An image built with a recent version of the cloud-init package can
   automatically access metadata passed through the configuration drive.
   The cloud-init package version 0.7.1 works with Ubuntu, Fedora
   based images (such as Red Hat Enterprise Linux) and openSUSE based
   images (such as SUSE Linux Enterprise Server).

-  If an image does not have the cloud-init package installed, you must
   customize the image to run a script that mounts the configuration
   drive on boot, reads the data from the drive, and takes appropriate
   action such as adding the public key to an account. You can read more
   details about how data is organized on the configuration drive.

-  If you use Xen with a configuration drive, use the
   ``xenapi_disable_agent`` configuration parameter to disable the
   agent.

**Guidelines**

-  Do not rely on the presence of the EC2 metadata in the configuration
   drive, because this content might be removed in a future release. For
   example, do not rely on files in the ``ec2`` directory.

-  When you create images that access configuration drive data and
   multiple directories are under the ``openstack`` directory, always
   select the highest API version by date that your consumer supports.
   For example, if your guest image supports the 2012-03-05, 2012-08-05,
   and 2013-04-13 versions, try 2013-04-13 first and fall back to a
   previous version if 2013-04-13 is not present.

Enable and access the configuration drive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. To enable the configuration drive, pass the ``--config-drive true``
   parameter to the :command:`openstack server create` command.

   The following example enables the configuration drive and passes user
   data, two files, and two key/value metadata pairs, all of which are
   accessible from the configuration drive:

   .. code-block:: console

      $ openstack server create --config-drive true --image my-image-name \
        --flavor 1 --key-name mykey --user-data ./my-user-data.txt \
        --file /etc/network/interfaces=/home/myuser/instance-interfaces \
        --file known_hosts=/home/myuser/.ssh/known_hosts \
        --property role=webservers --property essential=false MYINSTANCE

   You can also configure the Compute service to always create a
   configuration drive by setting the following option in the
   ``/etc/nova/nova.conf`` file:

   .. code-block:: console

      force_config_drive = true

   .. note::

      If a user passes the ``--config-drive true`` flag to the :command:`nova
      boot` command, an administrator cannot disable the configuration
      drive.

#. If your guest operating system supports accessing disk by label, you
   can mount the configuration drive as the
   ``/dev/disk/by-label/configurationDriveVolumeLabel`` device. In the
   following example, the configuration drive has the ``config-2``
   volume label:

   .. code-block:: console

      # mkdir -p /mnt/config
      # mount /dev/disk/by-label/config-2 /mnt/config

.. note::

   Ensure that you use at least version 0.3.1 of CirrOS for
   configuration drive support.

   If your guest operating system does not use ``udev``, the
   ``/dev/disk/by-label`` directory is not present.

   You can use the :command:`blkid` command to identify the block device that
   corresponds to the configuration drive. For example, when you boot
   the CirrOS image with the ``m1.tiny`` flavor, the device is
   ``/dev/vdb``:

   .. code-block:: console

      # blkid -t LABEL="config-2" -odevice

   .. code-block:: console

      /dev/vdb

   Once identified, you can mount the device:

   .. code-block:: console

      # mkdir -p /mnt/config
      # mount /dev/vdb /mnt/config

Configuration drive contents
----------------------------

In this example, the contents of the configuration drive are as follows::

   ec2/2009-04-04/meta-data.json
   ec2/2009-04-04/user-data
   ec2/latest/meta-data.json
   ec2/latest/user-data
   openstack/2012-08-10/meta_data.json
   openstack/2012-08-10/user_data
   openstack/content
   openstack/content/0000
   openstack/content/0001
   openstack/latest/meta_data.json
   openstack/latest/user_data

The files that appear on the configuration drive depend on the arguments
that you pass to the :command:`openstack server create` command.

OpenStack metadata format
-------------------------

The following example shows the contents of the
``openstack/2012-08-10/meta_data.json`` and
``openstack/latest/meta_data.json`` files. These files are identical.
The file contents are formatted for readability.

.. code-block:: json

   {
       "availability_zone": "nova",
       "files": [
           {
               "content_path": "/content/0000",
               "path": "/etc/network/interfaces"
           },
           {
               "content_path": "/content/0001",
               "path": "known_hosts"
           }
       ],
       "hostname": "test.novalocal",
       "launch_index": 0,
       "name": "test",
       "meta": {
           "role": "webservers",
           "essential": "false"
       },
       "public_keys": {
           "mykey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDBqUfVvCSez0/Wfpd8dLLgZXV9GtXQ7hnMN+Z0OWQUyebVEHey1CXuin0uY1cAJMhUq8j98SiW+cU0sU4J3x5l2+xi1bodDm1BtFWVeLIOQINpfV1n8fKjHB+ynPpe1F6tMDvrFGUlJs44t30BrujMXBe8Rq44cCk6wqyjATA3rQ== Generated by Nova\n"
       },
       "uuid": "83679162-1378-4288-a2d4-70e13ec132aa"
   }

Note the effect of the
``--file /etc/network/interfaces=/home/myuser/instance-interfaces``
argument that was passed to the :command:`openstack server create` command.
The contents of this file are contained in the ``openstack/content/0000``
file on the configuration drive, and the path is specified as
``/etc/network/interfaces`` in the ``meta_data.json`` file.

EC2 metadata format
-------------------

The following example shows the contents of the
``ec2/2009-04-04/meta-data.json`` and the ``ec2/latest/meta-data.json``
files. These files are identical. The file contents are formatted to
improve readability.

.. code-block:: json

   {
       "ami-id": "ami-00000001",
       "ami-launch-index": 0,
       "ami-manifest-path": "FIXME",
       "block-device-mapping": {
           "ami": "sda1",
           "ephemeral0": "sda2",
           "root": "/dev/sda1",
           "swap": "sda3"
       },
       "hostname": "test.novalocal",
       "instance-action": "none",
       "instance-id": "i-00000001",
       "instance-type": "m1.tiny",
       "kernel-id": "aki-00000002",
       "local-hostname": "test.novalocal",
       "local-ipv4": null,
       "placement": {
           "availability-zone": "nova"
       },
       "public-hostname": "test.novalocal",
       "public-ipv4": "",
       "public-keys": {
           "0": {
               "openssh-key": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDBqUfVvCSez0/Wfpd8dLLgZXV9GtXQ7hnMN+Z0OWQUyebVEHey1CXuin0uY1cAJMhUq8j98SiW+cU0sU4J3x5l2+xi1bodDm1BtFWVeLIOQINpfV1n8fKjHB+ynPpe1F6tMDvrFGUlJs44t30BrujMXBe8Rq44cCk6wqyjATA3rQ== Generated by Nova\n"
           }
       },
       "ramdisk-id": "ari-00000003",
       "reservation-id": "r-7lfps8wj",
       "security-groups": [
           "default"
       ]
   }

User data
---------

The ``openstack/2012-08-10/user_data``, ``openstack/latest/user_data``,
``ec2/2009-04-04/user-data``, and ``ec2/latest/user-data`` file are
present only if the ``--user-data`` flag and the contents of the user
data file are passed to the :command:`openstack server create` command.

Configuration drive format
--------------------------

The default format of the configuration drive as an ISO 9660 file
system. To explicitly specify the ISO 9660 format, add the following
line to the ``/etc/nova/nova.conf`` file:

.. code-block:: console

   config_drive_format=iso9660

By default, you cannot attach the configuration drive image as a CD
drive instead of as a disk drive. To attach a CD drive, add the
following line to the ``/etc/nova/nova.conf`` file:

.. code-block:: console

   config_drive_cdrom=true

For legacy reasons, you can configure the configuration drive to use
VFAT format instead of ISO 9660. It is unlikely that you would require
VFAT format because ISO 9660 is widely supported across operating
systems. However, to use the VFAT format, add the following line to the
``/etc/nova/nova.conf`` file:

.. code-block:: console

   config_drive_format=vfat

If you choose VFAT, the configuration drive is 64 MB.
