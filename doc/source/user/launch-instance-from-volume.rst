================================
Launch an instance from a volume
================================

You can boot instances from a volume instead of an image.

To complete these tasks, use these parameters on the
:command:`nova boot` command:

.. tabularcolumns:: |p{0.3\textwidth}|p{0.25\textwidth}|p{0.4\textwidth}|
.. list-table::
   :header-rows: 1
   :widths: 30 15 30

   * - Task
     - nova boot parameter
     - Information
   * - Boot an instance from an image and attach a non-bootable
       volume.
     - ``--block-device``
     -  :ref:`Boot_instance_from_image_and_attach_non-bootable_volume`
   * - Create a volume from an image and boot an instance from that
       volume.
     - ``--block-device``
     - :ref:`Create_volume_from_image_and_boot_instance`
   * - Boot from an existing source image, volume, or snapshot.
     - ``--block-device``
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
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create a non-bootable volume and attach that volume to an instance that
you boot from an image.

To create a non-bootable volume, do not create it from an image. The
volume must be entirely empty with no partition table and no file
system.

#. Create a non-bootable volume.

   .. code-block:: console

      $ openstack volume create --size 8 my-volume
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | attachments         | []                                   |
      | availability_zone   | nova                                 |
      | bootable            | false                                |
      | consistencygroup_id | None                                 |
      | created_at          | 2016-11-25T10:37:08.850997           |
      | description         | None                                 |
      | encrypted           | False                                |
      | id                  | b8f7bbec-6274-4cd7-90e7-60916a5e75d4 |
      | migration_status    | None                                 |
      | multiattach         | False                                |
      | name                | my-volume                            |
      | properties          |                                      |
      | replication_status  | disabled                             |
      | size                | 8                                    |
      | snapshot_id         | None                                 |
      | source_volid        | None                                 |
      | status              | creating                             |
      | type                | None                                 |
      | updated_at          | None                                 |
      | user_id             | 0678735e449149b0a42076e12dd54e28     |
      +---------------------+--------------------------------------+

#. List volumes.

   .. code-block:: console

      $ openstack volume list
      +--------------------------------------+--------------+-----------+------+-------------+
      | ID                                   | Name         | Status    | Size | Attached to |
      +--------------------------------------+--------------+-----------+------+-------------+
      | b8f7bbec-6274-4cd7-90e7-60916a5e75d4 | my-volume    | available |    8 |             |
      +--------------------------------------+--------------+-----------+------+-------------+

#. Boot an instance from an image and attach the empty volume to the
   instance.

   .. code-block:: console

      $ nova boot --flavor 2 --image 98901246-af91-43d8-b5e6-a4506aa8f369 \
        --block-device source=volume,id=d620d971-b160-4c4e-8652-2513d74e2080,dest=volume,shutdown=preserve \
        myInstanceWithVolume
      +--------------------------------------+--------------------------------------------+
      | Property                             | Value                                      |
      +--------------------------------------+--------------------------------------------+
      | OS-DCF:diskConfig                    | MANUAL                                     |
      | OS-EXT-AZ:availability_zone          | nova                                       |
      | OS-EXT-SRV-ATTR:host                 | -                                          |
      | OS-EXT-SRV-ATTR:hypervisor_hostname  | -                                          |
      | OS-EXT-SRV-ATTR:instance_name        | instance-00000004                          |
      | OS-EXT-STS:power_state               | 0                                          |
      | OS-EXT-STS:task_state                | scheduling                                 |
      | OS-EXT-STS:vm_state                  | building                                   |
      | OS-SRV-USG:launched_at               | -                                          |
      | OS-SRV-USG:terminated_at             | -                                          |
      | accessIPv4                           |                                            |
      | accessIPv6                           |                                            |
      | adminPass                            | ZaiYeC8iucgU                               |
      | config_drive                         |                                            |
      | created                              | 2014-05-09T16:34:50Z                       |
      | flavor                               | m1.small (2)                               |
      | hostId                               |                                            |
      | id                                   | 1e1797f3-1662-49ff-ae8c-a77e82ee1571       |
      | image                                | cirros-0.3.5-x86_64-uec (98901246-af91-... |
      | key_name                             | -                                          |
      | metadata                             | {}                                         |
      | name                                 | myInstanceWithVolume                       |
      | os-extended-volumes:volumes_attached | [{"id": "d620d971-b160-4c4e-8652-2513d7... |
      | progress                             | 0                                          |
      | security_groups                      | default                                    |
      | status                               | BUILD                                      |
      | tenant_id                            | ccef9e62b1e645df98728fb2b3076f27           |
      | updated                              | 2014-05-09T16:34:51Z                       |
      | user_id                              | fef060ae7bfd4024b3edb97dff59017a           |
      +--------------------------------------+--------------------------------------------+

.. _Create_volume_from_image_and_boot_instance:

Create volume from image and boot instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can create a volume from an existing image, volume, or snapshot.
This procedure shows you how to create a volume from an image, and use
the volume to boot an instance.

#. List the available images.

   .. code-block:: console

      $ openstack image list
      +-----------------+---------------------------------+--------+
      | ID              | Name                            | Status |
      +-----------------+---------------------------------+--------+
      | 484e05af-a14... | Fedora-x86_64-20-20131211.1-sda | active |
      | 98901246-af9... | cirros-0.3.5-x86_64-uec         | active |
      | b6e95589-7eb... | cirros-0.3.5-x86_64-uec-kernel  | active |
      | c90893ea-e73... | cirros-0.3.5-x86_64-uec-ramdisk | active |
      +-----------------+---------------------------------+--------+

   Note the ID of the image that you want to use to create a volume.

   If you want to create a volume to a specific storage backend, you need
   to use an image which has *cinder_img_volume_type* property.
   In this case, a new volume will be created as *storage_backend1* volume
   type.

   .. code-block:: console

      $ openstack image show 98901246-af9d-4b61-bea8-09cc6dc41829
      +------------------+------------------------------------------------------+
      | Field            | Value                                                |
      +------------------+------------------------------------------------------+
      | checksum         | ee1eca47dc88f4879d8a229cc70a07c6                     |
      | container_format | bare                                                 |
      | created_at       | 2016-10-08T14:59:05Z                                 |
      | disk_format      | qcow2                                                |
      | file             | /v2/images/9fef3b2d-c35d-4b61-bea8-09cc6dc41829/file |
      | id               | 98901246-af9d-4b61-bea8-09cc6dc41829                 |
      | min_disk         | 0                                                    |
      | min_ram          | 0                                                    |
      | name             | cirros-0.3.5-x86_64-uec                              |
      | owner            | 8d8ef3cdf2b54c25831cbb409ad9ae86                     |
      | protected        | False                                                |
      | schema           | /v2/schemas/image                                    |
      | size             | 13287936                                             |
      | status           | active                                               |
      | tags             |                                                      |
      | updated_at       | 2016-10-19T09:12:52Z                                 |
      | virtual_size     | None                                                 |
      | visibility       | public                                               |
      +------------------+------------------------------------------------------+

#. List the available flavors.

   .. code-block:: console

      $ openstack flavor list
      +-----+-----------+-------+------+-----------+-------+-----------+
      | ID  | Name      |   RAM | Disk | Ephemeral | VCPUs | Is_Public |
      +-----+-----------+-------+------+-----------+-------+-----------+
      | 1   | m1.tiny   |   512 |    1 |         0 |     1 | True      |
      | 2   | m1.small  |  2048 |   20 |         0 |     1 | True      |
      | 3   | m1.medium |  4096 |   40 |         0 |     2 | True      |
      | 4   | m1.large  |  8192 |   80 |         0 |     4 | True      |
      | 5   | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
      +-----+-----------+-------+------+-----------+-------+-----------+

   Note the ID of the flavor that you want to use to create a volume.

#. To create a bootable volume from an image and launch an instance from
   this volume, use the ``--block-device`` parameter with the ``nova boot``
   command.

   For example:

   .. code-block:: console

      $ nova boot --flavor FLAVOR --block-device \
        source=SOURCE,id=ID,dest=DEST,size=SIZE,shutdown=PRESERVE,bootindex=INDEX \
        NAME

   The parameters are:

   - ``--flavor``
     The flavor ID or name.

   - ``--block-device``
     source=SOURCE,id=ID,dest=DEST,size=SIZE,shutdown=PRESERVE,bootindex=INDEX

     **source=SOURCE**
       The type of object used to create the block device. Valid values
       are ``volume``, ``snapshot``, ``image``, and ``blank``.

     **id=ID**
       The ID of the source object.

     **dest=DEST**
       The type of the target virtual device. Valid values are ``volume``
       and ``local``.

     **size=SIZE**
       The size of the volume that is created.

     **shutdown={preserve\|remove}**
       What to do with the volume when the instance is deleted.
       ``preserve`` does not delete the volume. ``remove`` deletes the
       volume.

     **bootindex=INDEX**
       Orders the boot disks. Use ``0`` to boot from this volume.

   - ``NAME``. The name for the server.

   See the `nova boot`_ command documentation and :doc:`block-device-mapping`
   for more details on these parameters.

   .. note:: As of the Stein release, the ``openstack server create`` command
      does not support creating a volume-backed server from a source image like
      the ``nova boot`` command. The next steps will show how to create a
      bootable volume from an image and then create a server from that boot
      volume using the ``openstack server create`` command.

#. Create a bootable volume from an image. Cinder makes a volume bootable
   when ``--image`` parameter is passed.

   .. code-block:: console

      $ openstack volume create --image IMAGE_ID --size SIZE_IN_GB bootable_volume

   .. note::

      A bootable encrypted volume can also be created by adding the
      `--type ENCRYPTED_VOLUME_TYPE` parameter to the volume create command:

   .. code-block:: console

      $ openstack volume create --type ENCRYPTED_VOLUME_TYPE --image IMAGE_ID --size SIZE_IN_GB bootable_volume
      +---------------------+--------------------------------------+
      | Field               | Value                                |
      +---------------------+--------------------------------------+
      | attachments         | []                                   |
      | availability_zone   | nova                                 |
      | bootable            | false                                |
      | consistencygroup_id | None                                 |
      | created_at          | 2017-06-13T18:59:57.626872           |
      | description         | None                                 |
      | encrypted           | True                                 |
      | id                  | ded57a86-5b51-43ab-b70e-9bc0f91ef4ab |
      | multiattach         | False                                |
      | name                | bootable_volume                      |
      | properties          |                                      |
      | replication_status  | None                                 |
      | size                | 1                                    |
      | snapshot_id         | None                                 |
      | source_volid        | None                                 |
      | status              | creating                             |
      | type                | LUKS                                 |
      | updated_at          | None                                 |
      | user_id             | 459ae34ffcd94edab0c128ed616bb19f     |
      +---------------------+--------------------------------------+


   This requires an encrypted volume type, which must be created ahead of
   time by an admin.  Refer to
   :horizon-doc:`admin/manage-volumes.html#create-an-encrypted-volume-type`.
   in the OpenStack Horizon Administration Guide.

#. Create a VM from previously created bootable volume. The volume is not
   deleted when the instance is terminated.

   .. note:: The example here uses the ``--volume`` option for simplicity. The
      ``--block-device-mapping`` option could also be used for more granular control
      over the parameters. See the `openstack server create`_ documentation for
      details.

   .. code-block:: console

      $ openstack server create --flavor 2 --volume VOLUME_ID myInstanceFromVolume
      +--------------------------------------+--------------------------------+
      | Field                                | Value                          |
      +--------------------------------------+--------------------------------+
      | OS-EXT-STS:task_state                | scheduling                     |
      | image                                | Attempt to boot from volume    |
      |                                      | - no image supplied            |
      | OS-EXT-STS:vm_state                  | building                       |
      | OS-EXT-SRV-ATTR:instance_name        | instance-00000003              |
      | OS-SRV-USG:launched_at               | None                           |
      | flavor                               | m1.small                       |
      | id                                   | 2e65c854-dba9-4f68-8f08-fe3... |
      | security_groups                      | [{u'name': u'default'}]        |
      | user_id                              | 352b37f5c89144d4ad053413926... |
      | OS-DCF:diskConfig                    | MANUAL                         |
      | accessIPv4                           |                                |
      | accessIPv6                           |                                |
      | progress                             | 0                              |
      | OS-EXT-STS:power_state               | 0                              |
      | OS-EXT-AZ:availability_zone          | nova                           |
      | config_drive                         |                                |
      | status                               | BUILD                          |
      | updated                              | 2014-02-02T13:29:54Z           |
      | hostId                               |                                |
      | OS-EXT-SRV-ATTR:host                 | None                           |
      | OS-SRV-USG:terminated_at             | None                           |
      | key_name                             | None                           |
      | OS-EXT-SRV-ATTR:hypervisor_hostname  | None                           |
      | name                                 | myInstanceFromVolume           |
      | adminPass                            | TzjqyGsRcJo9                   |
      | tenant_id                            | f7ac731cc11f40efbc03a9f9e1d... |
      | created                              | 2014-02-02T13:29:53Z           |
      | os-extended-volumes:volumes_attached | [{"id": "2fff50ab..."}]        |
      | metadata                             | {}                             |
      +--------------------------------------+--------------------------------+

#. List volumes to see the bootable volume and its attached
   ``myInstanceFromVolume`` instance.

   .. code-block:: console

      $ openstack volume list
      +---------------------+-----------------+--------+------+---------------------------------+
      | ID                  | Name            | Status | Size | Attached to                     |
      +---------------------+-----------------+--------+------+---------------------------------+
      | c612f739-8592-44c4- | bootable_volume | in-use |  10  | Attached to myInstanceFromVolume|
      | b7d4-0fee2fe1da0c   |                 |        |      | on /dev/vda                     |
      +---------------------+-----------------+--------+------+---------------------------------+

.. _nova boot: https://docs.openstack.org/python-novaclient/latest/cli/nova.html#nova-boot
.. _openstack server create: https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/server.html#server-create

.. _Attach_swap_or_ephemeral_disk_to_an_instance:

Attach swap or ephemeral disk to an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the ``nova boot`` ``--swap`` parameter to attach a swap disk on boot
or the ``nova boot`` ``--ephemeral`` parameter to attach an ephemeral
disk on boot. When you terminate the instance, both disks are deleted.

Boot an instance with a 512 MB swap disk and 2 GB ephemeral disk.

.. code-block:: console

   $ nova boot --flavor FLAVOR --image IMAGE_ID --swap 512 \
     --ephemeral size=2 NAME

.. note::

   The flavor defines the maximum swap and ephemeral disk size. You
   cannot exceed these maximum values.
