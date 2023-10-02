================================
Launch an instance from a volume
================================

You can boot instances from a volume instead of an image.

To complete these tasks, use these parameters on the
:command:`openstack server create` command:

.. tabularcolumns:: |p{0.3\textwidth}|p{0.25\textwidth}|p{0.4\textwidth}|
.. list-table::
   :header-rows: 1
   :widths: 30 15 30

   * - Task
     - openstack server create parameter(s)
     - Information
   * - Boot an instance from an image and attach a non-bootable
       volume.
     - ``--block-device``
     -  :ref:`Boot_instance_from_image_and_attach_non-bootable_volume`
   * - Create a volume from an image and boot an instance from that
       volume.
     - ``--boot-from-volume`` and ``--image``; ``--block-device``
     - :ref:`Create_volume_from_image_and_boot_instance`
   * - Boot from an existing source image, volume, or snapshot.
     - ``--volume`` or ``--snapshot``; ``--block-device``
     - :ref:`Create_volume_from_image_and_boot_instance`
   * - Attach a swap disk to an instance.
     - ``--swap``
     - :ref:`Attach_swap_or_ephemeral_disk_to_an_instance`
   * - Attach an ephemeral disk to an instance.
     - ``--ephemeral``
     - :ref:`Attach_swap_or_ephemeral_disk_to_an_instance`

.. note::

   To attach a volume to a running instance, refer to the
   :cinder-doc:`Cinder documentation
   <cli/cli-manage-volumes.html#attach-a-volume-to-an-instance>`.

.. note::

   The maximum limit on the number of disk devices allowed to attach to
   a single server is configurable with the option
   :oslo.config:option:`compute.max_disk_devices_to_attach`.

.. _Boot_instance_from_image_and_attach_non-bootable_volume:

Boot instance from image and attach non-bootable volume
-------------------------------------------------------

You can create a non-bootable volume and attach that volume to an instance that
you boot from an image.

To create a non-bootable volume, do not create it from an image. The
volume must be entirely empty with no partition table and no file
system.

#. Create a non-bootable volume.

   .. code-block:: console

      $ openstack volume create --size 8 test-volume
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | attachments         | []                                   |
      | availability_zone   | nova                                 |
      | bootable            | false                                |
      | consistencygroup_id | None                                 |
      | created_at          | 2021-06-01T15:01:31.000000           |
      | description         | None                                 |
      | encrypted           | False                                |
      | id                  | 006efd7a-48a8-4c75-bafb-6b483199d284 |
      | migration_status    | None                                 |
      | multiattach         | False                                |
      | name                | test-volume                          |
      | properties          |                                      |
      | replication_status  | None                                 |
      | size                | 8                                    |
      | snapshot_id         | None                                 |
      | source_volid        | None                                 |
      | status              | creating                             |
      | type                | lvmdriver-1                          |
      | updated_at          | None                                 |
      | user_id             | 0a4d2edb9042412ba4f719a547d42f79     |
      +---------------------+--------------------------------------+

#. List volumes and confirm that it is in the ``available`` state.

   .. code-block:: console

      $ openstack volume list
      +--------------------------------------+-------------+-----------+------+-------------+
      | ID                                   | Name        | Status    | Size | Attached to |
      +--------------------------------------+-------------+-----------+------+-------------+
      | 006efd7a-48a8-4c75-bafb-6b483199d284 | test-volume | available |    8 |             |
      +--------------------------------------+-------------+-----------+------+-------------+

#. Create an instance, specifying the volume as a block device to attach.

   .. code-block:: console

      $ openstack server create \
          --flavor $FLAVOR --image $IMAGE --network $NETWORK \
          --block-device uuid=006efd7a-48a8-4c75-bafb-6b483199d284,source_type=volume,destination_type=volume \
          --wait test-server
      +-------------------------------------+-----------------------------------------------------------------+
      | Field                               | Value                                                           |
      +-------------------------------------+-----------------------------------------------------------------+
      | OS-DCF:diskConfig                   | MANUAL                                                          |
      | OS-EXT-AZ:availability_zone         | nova                                                            |
      | OS-EXT-SRV-ATTR:host                | devstack-ubuntu2004                                             |
      | OS-EXT-SRV-ATTR:hypervisor_hostname | devstack-ubuntu2004                                             |
      | OS-EXT-SRV-ATTR:instance_name       | instance-00000008                                               |
      | OS-EXT-STS:power_state              | Running                                                         |
      | OS-EXT-STS:task_state               | None                                                            |
      | OS-EXT-STS:vm_state                 | active                                                          |
      | OS-SRV-USG:launched_at              | 2021-06-01T15:13:48.000000                                      |
      | OS-SRV-USG:terminated_at            | None                                                            |
      | accessIPv4                          |                                                                 |
      | accessIPv6                          |                                                                 |
      | addresses                           | private=10.0.0.55, fde3:4790:906b:0:f816:3eff:fed5:ebd9         |
      | adminPass                           | CZ76LZ9pNXzt                                                    |
      | config_drive                        |                                                                 |
      | created                             | 2021-06-01T15:13:37Z                                            |
      | flavor                              | m1.tiny (1)                                                     |
      | hostId                              | 425d65fe75c1e53cecbd32d3e686314235507b6edebbeaa56ff341c7        |
      | id                                  | 446d1b00-b729-49b3-9dab-40a3fbe190cf                            |
      | image                               | cirros-0.5.1-x86_64-disk (44d317a3-6183-4063-868b-aa0728576f5f) |
      | key_name                            | None                                                            |
      | name                                | test-server                                                     |
      | progress                            | 0                                                               |
      | project_id                          | ae93f388f934458c8e6583f8ab0dba2d                                |
      | properties                          |                                                                 |
      | security_groups                     | name='default'                                                  |
      | status                              | ACTIVE                                                          |
      | updated                             | 2021-06-01T15:13:49Z                                            |
      | user_id                             | 0a4d2edb9042412ba4f719a547d42f79                                |
      | volumes_attached                    | id='006efd7a-48a8-4c75-bafb-6b483199d284'                       |
      +-------------------------------------+-----------------------------------------------------------------+

#. List volumes once again to ensure the status has changed to ``in-use`` and
   the volume is correctly reporting the attachment.

   .. code-block:: console

      $ openstack volume list
      +--------------------------------------+-------------+--------+------+--------------------------------------+
      | ID                                   | Name        | Status | Size | Attached to                          |
      +--------------------------------------+-------------+--------+------+--------------------------------------+
      | 006efd7a-48a8-4c75-bafb-6b483199d284 | test-volume | in-use |    1 | Attached to test-server on /dev/vdb  |
      +--------------------------------------+-------------+--------+------+--------------------------------------+

.. _Create_volume_from_image_and_boot_instance:

Boot instance from volume
-------------------------

You can create a bootable volume from an existing image, volume, or snapshot.
This procedure shows you how to create a volume from an image and use the
volume to boot an instance.

#. List available images, noting the ID of the image that you wish to use.

   .. code-block:: console

      $ openstack image list
      +--------------------------------------+--------------------------+--------+
      | ID                                   | Name                     | Status |
      +--------------------------------------+--------------------------+--------+
      | 44d317a3-6183-4063-868b-aa0728576f5f | cirros-0.5.1-x86_64-disk | active |
      +--------------------------------------+--------------------------+--------+

#. Create an instance, using the chosen image and requesting "boot from volume"
   behavior.

   .. code-block:: console

      $ openstack server create \
          --flavor $FLAVOR --network $NETWORK \
          --image 44d317a3-6183-4063-868b-aa0728576f5f --boot-from-volume 10 \
          --wait test-server
      +-------------------------------------+----------------------------------------------------------+
      | Field                               | Value                                                    |
      +-------------------------------------+----------------------------------------------------------+
      | OS-DCF:diskConfig                   | MANUAL                                                   |
      | OS-EXT-AZ:availability_zone         | nova                                                     |
      | OS-EXT-SRV-ATTR:host                | devstack-ubuntu2004                                      |
      | OS-EXT-SRV-ATTR:hypervisor_hostname | devstack-ubuntu2004                                      |
      | OS-EXT-SRV-ATTR:instance_name       | instance-0000000c                                        |
      | OS-EXT-STS:power_state              | Running                                                  |
      | OS-EXT-STS:task_state               | None                                                     |
      | OS-EXT-STS:vm_state                 | active                                                   |
      | OS-SRV-USG:launched_at              | 2021-06-01T16:02:06.000000                               |
      | OS-SRV-USG:terminated_at            | None                                                     |
      | accessIPv4                          |                                                          |
      | accessIPv6                          |                                                          |
      | addresses                           | private=10.0.0.3, fde3:4790:906b:0:f816:3eff:fe40:bdd    |
      | adminPass                           | rqT3RUYYa5H5                                             |
      | config_drive                        |                                                          |
      | created                             | 2021-06-01T16:01:55Z                                     |
      | flavor                              | m1.tiny (1)                                              |
      | hostId                              | 425d65fe75c1e53cecbd32d3e686314235507b6edebbeaa56ff341c7 |
      | id                                  | 69b09fa0-6f24-4924-8311-c9bcdeb90dcb                     |
      | image                               | N/A (booted from volume)                                 |
      | key_name                            | None                                                     |
      | name                                | test-server                                              |
      | progress                            | 0                                                        |
      | project_id                          | ae93f388f934458c8e6583f8ab0dba2d                         |
      | properties                          |                                                          |
      | security_groups                     | name='default'                                           |
      | status                              | ACTIVE                                                   |
      | updated                             | 2021-06-01T16:02:07Z                                     |
      | user_id                             | 0a4d2edb9042412ba4f719a547d42f79                         |
      | volumes_attached                    | id='673cbfcb-351c-42cb-9659-bca5b2a0361c'                |
      +-------------------------------------+----------------------------------------------------------+

   .. note::

      Volumes created in this manner will not be deleted when the server is
      deleted and will need to be manually deleted afterwards. If you wish to
      change this behavior, you will need to pre-create the volume manually as
      discussed below.

#. List volumes to ensure a new volume has been created and that its status is
   ``in-use`` and the volume is correctly reporting the attachment.

   .. code-block:: console


      $ openstack volume list
      +--------------------------------------+------+--------+------+--------------------------------------+
      | ID                                   | Name | Status | Size | Attached to                          |
      +--------------------------------------+------+--------+------+--------------------------------------+
      | 673cbfcb-351c-42cb-9659-bca5b2a0361c |      | in-use |    1 | Attached to test-server on /dev/vda  |
      +--------------------------------------+------+--------+------+--------------------------------------+

      $ openstack server volume list test-server
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+
      | ID                                   | Device   | Server ID                            | Volume ID                            |
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+
      | 673cbfcb-351c-42cb-9659-bca5b2a0361c | /dev/vda | 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005 | 673cbfcb-351c-42cb-9659-bca5b2a0361c |
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+

Rather than relying on nova to create the volume from the image, it is also
possible to pre-create the volume before creating the instance. This can be
useful when you want more control over the created volume, such as enabling
encryption.

#. List available images, noting the ID of the image that you wish to use.

   .. code-block:: console

      $ openstack image list
      +--------------------------------------+--------------------------+--------+
      | ID                                   | Name                     | Status |
      +--------------------------------------+--------------------------+--------+
      | 44d317a3-6183-4063-868b-aa0728576f5f | cirros-0.5.1-x86_64-disk | active |
      +--------------------------------------+--------------------------+--------+

#. Create a bootable volume from the chosen image.

   Cinder makes a volume bootable when ``--image`` parameter is passed.

   .. code-block:: console

      $ openstack volume create \
          --image 44d317a3-6183-4063-868b-aa0728576f5f --size 10 \
          test-volume
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | attachments         | []                                   |
      | availability_zone   | nova                                 |
      | bootable            | false                                |
      | consistencygroup_id | None                                 |
      | created_at          | 2021-06-01T15:40:56.000000           |
      | description         | None                                 |
      | encrypted           | False                                |
      | id                  | 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005 |
      | migration_status    | None                                 |
      | multiattach         | False                                |
      | name                | test-volume                          |
      | properties          |                                      |
      | replication_status  | None                                 |
      | size                | 10                                   |
      | snapshot_id         | None                                 |
      | source_volid        | None                                 |
      | status              | creating                             |
      | type                | lvmdriver-1                          |
      | updated_at          | None                                 |
      | user_id             | 0a4d2edb9042412ba4f719a547d42f79     |
      +---------------------+--------------------------------------+

   .. note::

      If you want to create a volume to a specific storage backend, you need
      to use an image which has the ``cinder_img_volume_type`` property. For
      more information, refer to the :cinder-doc:`cinder docs
      </cli/cli-manage-volumes.html#volume-types>`.

   .. note::

      A bootable encrypted volume can also be created by adding the
      ``--type ENCRYPTED_VOLUME_TYPE`` parameter to the volume create command.
      For example:

      .. code-block:: console

         $ openstack volume create \
             --type ENCRYPTED_VOLUME_TYPE --image IMAGE --size SIZE \
             test-volume

      This requires an encrypted volume type which must be created ahead of
      time by an admin. Refer to
      :horizon-doc:`the horizon documentation <admin/manage-volumes.html#create-an-encrypted-volume-type>`.
      for more information.

#. Create an instance, specifying the volume as the boot device.

   .. code-block:: console

      $ openstack server create \
          --flavor $FLAVOR --network $NETWORK \
          --volume 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005\
          --wait test-server
      +-------------------------------------+----------------------------------------------------------+
      | Field                               | Value                                                    |
      +-------------------------------------+----------------------------------------------------------+
      | OS-DCF:diskConfig                   | MANUAL                                                   |
      | OS-EXT-AZ:availability_zone         | nova                                                     |
      | OS-EXT-SRV-ATTR:host                | devstack-ubuntu2004                                      |
      | OS-EXT-SRV-ATTR:hypervisor_hostname | devstack-ubuntu2004                                      |
      | OS-EXT-SRV-ATTR:instance_name       | instance-0000000a                                        |
      | OS-EXT-STS:power_state              | Running                                                  |
      | OS-EXT-STS:task_state               | None                                                     |
      | OS-EXT-STS:vm_state                 | active                                                   |
      | OS-SRV-USG:launched_at              | 2021-06-01T15:43:21.000000                               |
      | OS-SRV-USG:terminated_at            | None                                                     |
      | accessIPv4                          |                                                          |
      | accessIPv6                          |                                                          |
      | addresses                           | private=10.0.0.47, fde3:4790:906b:0:f816:3eff:fe89:b004  |
      | adminPass                           | ueX74zzHWqL4                                             |
      | config_drive                        |                                                          |
      | created                             | 2021-06-01T15:43:13Z                                     |
      | flavor                              | m1.tiny (1)                                              |
      | hostId                              | 425d65fe75c1e53cecbd32d3e686314235507b6edebbeaa56ff341c7 |
      | id                                  | 367b7d42-627c-4d10-a2a0-f759501499a6                     |
      | image                               | N/A (booted from volume)                                 |
      | key_name                            | None                                                     |
      | name                                | test-server                                              |
      | progress                            | 0                                                        |
      | project_id                          | ae93f388f934458c8e6583f8ab0dba2d                         |
      | properties                          |                                                          |
      | security_groups                     | name='default'                                           |
      | status                              | ACTIVE                                                   |
      | updated                             | 2021-06-01T15:43:22Z                                     |
      | user_id                             | 0a4d2edb9042412ba4f719a547d42f79                         |
      | volumes_attached                    | id='9c7f68d4-4d84-4c1e-83af-b8c6a56ad005'                |
      +-------------------------------------+----------------------------------------------------------+

   .. note::

      The example here uses the ``--volume`` option for simplicity. The
      ``--block-device`` option could also be used for more granular control
      over the parameters. See the `openstack server create`__ documentation for
      details.

      .. __: https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/server.html#server-create

#. List volumes once again to ensure the status has changed to ``in-use`` and
   the volume is correctly reporting the attachment.

   .. code-block:: console

      $ openstack volume list
      +--------------------------------------+-------------+--------+------+--------------------------------------+
      | ID                                   | Name        | Status | Size | Attached to                          |
      +--------------------------------------+-------------+--------+------+--------------------------------------+
      | 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005 | test-volume | in-use |   10 | Attached to test-server on /dev/vda  |
      +--------------------------------------+-------------+--------+------+--------------------------------------+

      $ openstack server volume list test-server
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+
      | ID                                   | Device   | Server ID                            | Volume ID                            |
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+
      | 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005 | /dev/vda | c2368c38-6a7d-4fe8-bc4e-483e90e7608b | 9c7f68d4-4d84-4c1e-83af-b8c6a56ad005 |
      +--------------------------------------+----------+--------------------------------------+--------------------------------------+

.. _Attach_swap_or_ephemeral_disk_to_an_instance:

Attach swap or ephemeral disk to an instance
--------------------------------------------

Use the ``--swap`` option of the ``openstack server`` command to attach a swap
disk on boot or the ``--ephemeral`` option to attach an ephemeral disk on boot.
The latter can be specified multiple times. When you terminate the instance,
both disks are deleted.

Boot an instance with a 512 MB swap disk and 2 GB ephemeral disk.

.. code-block:: console

   $ openstack server create \
       --flavor FLAVOR --image IMAGE --network NETWORK \
       --ephemeral size=2 --swap 512
       --wait test-server

.. note::

   The flavor defines the maximum swap and ephemeral disk size. You
   cannot exceed these maximum values.
