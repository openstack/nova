================
Launch instances
================

Instances are virtual machines that run inside the cloud.

Before you can launch an instance, gather the following parameters:

- The **instance source** can be an image, snapshot, or block storage
  volume that contains an image or snapshot.

- A **name** for your instance.

- The **flavor** for your instance, which defines the compute, memory,
  and storage capacity of nova computing instances. A flavor is an
  available hardware configuration for a server. It defines the size of
  a virtual server that can be launched.

- Any **user data** files. A user data file is a special key in the
  metadata service that holds a file that cloud-aware applications in
  the guest instance can access. For example, one application that uses
  user data is the
  `cloud-init <https://help.ubuntu.com/community/CloudInit>`__ system,
  which is an open-source package from Ubuntu that is available on
  various Linux distributions and that handles early initialization of
  a cloud instance.

- Access and security credentials, which include one or both of the
  following credentials:

  - A **key pair** for your instance, which are SSH credentials that
    are injected into images when they are launched. For the key pair
    to be successfully injected, the image must contain the
    ``cloud-init`` package. Create at least one key pair for each
    project. If you already have generated a key pair with an external
    tool, you can import it into OpenStack. You can use the key pair
    for multiple instances that belong to that project.

  - A **security group** that defines which incoming network traffic
    is forwarded to instances. Security groups hold a set of firewall
    policies, known as *security group rules*.

- If needed, you can assign a **floating (public) IP address** to a
  running instance to make it accessible from outside the cloud. See
  :doc:`manage-ip-addresses`.

- You can also attach a block storage device, or **volume**, for
  persistent storage.

.. note::

   Instances that use the default security group cannot, by default, be
   accessed from any IP address outside of the cloud. If you want those
   IP addresses to access the instances, you must modify the rules for
   the default security group.

After you gather the parameters that you need to launch an instance,
you can launch it from an :doc:`image<launch-instance-from-image>`
or a :doc:`volume<launch-instance-from-volume>`. You can launch an
instance directly from one of the available OpenStack images or from
an image that you have copied to a persistent volume. The OpenStack
Image service provides a pool of images that are accessible to members
of different projects.

Gather parameters to launch an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Before you begin, source the OpenStack RC file.

#. Create a flavor.

   Creating a flavor is typically only available to administrators of a cloud
   because this has implications for scheduling efficiently in the cloud.

   .. code-block:: console

      $  openstack flavor create --ram 512 --disk 1 --vcpus 1 m1.tiny

#. List the available flavors.

   .. code-block:: console

      $ openstack flavor list

   Note the ID of the flavor that you want to use for your instance::

    +-----+-----------+-------+------+-----------+-------+-----------+
    | ID  | Name      |   RAM | Disk | Ephemeral | VCPUs | Is_Public |
    +-----+-----------+-------+------+-----------+-------+-----------+
    | 1   | m1.tiny   |   512 |    1 |         0 |     1 | True      |
    | 2   | m1.small  |  2048 |   20 |         0 |     1 | True      |
    | 3   | m1.medium |  4096 |   40 |         0 |     2 | True      |
    | 4   | m1.large  |  8192 |   80 |         0 |     4 | True      |
    | 5   | m1.xlarge | 16384 |  160 |         0 |     8 | True      |
    +-----+-----------+-------+------+-----------+-------+-----------+

#. List the available images.

   .. code-block:: console

      $ openstack image list

   Note the ID of the image from which you want to boot your instance::

    +--------------------------------------+---------------------------------+--------+
    | ID                                   | Name                            | Status |
    +--------------------------------------+---------------------------------+--------+
    | 397e713c-b95b-4186-ad46-6126863ea0a9 | cirros-0.3.5-x86_64-uec         | active |
    | df430cc2-3406-4061-b635-a51c16e488ac | cirros-0.3.5-x86_64-uec-kernel  | active |
    | 3cf852bd-2332-48f4-9ae4-7d926d50945e | cirros-0.3.5-x86_64-uec-ramdisk | active |
    +--------------------------------------+---------------------------------+--------+

   You can also filter the image list by using :command:`grep` to find a specific
   image, as follows:

   .. code-block:: console

      $ openstack image list | grep 'kernel'

      | df430cc2-3406-4061-b635-a51c16e488ac | cirros-0.3.5-x86_64-uec-kernel  | active |

#. List the available security groups.

   .. code-block:: console

      $ openstack security group list

   .. note::

      If you are an admin user, this command will list groups for all tenants.

   Note the ID of the security group that you want to use for your instance::

    +--------------------------------------+---------+------------------------+----------------------------------+
    | ID                                   | Name    | Description            | Project                          |
    +--------------------------------------+---------+------------------------+----------------------------------+
    | b0d78827-0981-45ef-8561-93aee39bbd9f | default | Default security group | 5669caad86a04256994cdf755df4d3c1 |
    | ec02e79e-83e1-48a5-86ad-14ab9a8c375f | default | Default security group | 1eaaf6ede7a24e78859591444abf314a |
    +--------------------------------------+---------+------------------------+----------------------------------+

   If you have not created any security groups, you can assign the instance
   to only the default security group.

   You can view rules for a specified security group:

   .. code-block:: console

      $ openstack security group rule list default

#. List the available key pairs, and note the key pair name that you use for
   SSH access.

   .. code-block:: console

      $ openstack keypair list

Launch an instance
~~~~~~~~~~~~~~~~~~

You can launch an instance from various sources.

.. toctree::
   :maxdepth: 2

   launch-instance-from-image.rst
   launch-instance-from-volume.rst
   launch-instance-using-ISO-image.rst

