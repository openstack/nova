================================
Launch an instance from an image
================================

Follow the steps below to launch an instance from an image.

#. After you gather required parameters, run the following command to
   launch an instance. Specify the server name, flavor ID, and image ID.

   .. code-block:: console

      $ openstack server create --flavor FLAVOR_ID --image IMAGE_ID --key-name KEY_NAME \
        --user-data USER_DATA_FILE --security-group SEC_GROUP_NAME --property KEY=VALUE \
        INSTANCE_NAME

   Optionally, you can provide a key name for access control and a security
   group for security. You can also include metadata key and value pairs.
   For example, you can add a description for your server by providing the
   ``--property description="My Server"`` parameter.

   You can pass :ref:`user data <metadata-userdata>` in a local file at
   instance launch by using the ``--user-data USER-DATA-FILE`` parameter.

   .. important::

      If you boot an instance with an INSTANCE_NAME greater than 63 characters,
      Compute truncates it automatically when turning it into a host name to
      ensure the correct work of dnsmasq. The corresponding warning is written
      into the ``neutron-dnsmasq.log`` file.

   The following command launches the ``MyCirrosServer`` instance with the
   ``m1.small`` flavor (ID of ``1``), ``cirros-0.3.2-x86_64-uec`` image (ID
   of ``397e713c-b95b-4186-ad46-6126863ea0a9``), ``default`` security
   group, ``KeyPair01`` key, and a user data file called
   ``cloudinit.file``:

   .. code-block:: console

      $ openstack server create --flavor 1 --image 397e713c-b95b-4186-ad46-6126863ea0a9 \
        --security-group default --key-name KeyPair01 --user-data cloudinit.file \
        myCirrosServer

   Depending on the parameters that you provide, the command returns a list
   of server properties.

   .. code-block:: console

      +--------------------------------------+-----------------------------------------------+
      | Field                                | Value                                         |
      +--------------------------------------+-----------------------------------------------+
      | OS-DCF:diskConfig                    | MANUAL                                        |
      | OS-EXT-AZ:availability_zone          |                                               |
      | OS-EXT-SRV-ATTR:host                 | None                                          |
      | OS-EXT-SRV-ATTR:hypervisor_hostname  | None                                          |
      | OS-EXT-SRV-ATTR:instance_name        |                                               |
      | OS-EXT-STS:power_state               | NOSTATE                                       |
      | OS-EXT-STS:task_state                | scheduling                                    |
      | OS-EXT-STS:vm_state                  | building                                      |
      | OS-SRV-USG:launched_at               | None                                          |
      | OS-SRV-USG:terminated_at             | None                                          |
      | accessIPv4                           |                                               |
      | accessIPv6                           |                                               |
      | addresses                            |                                               |
      | adminPass                            | E4Ksozt4Efi8                                  |
      | config_drive                         |                                               |
      | created                              | 2016-11-30T14:48:05Z                          |
      | flavor                               | m1.tiny                                       |
      | hostId                               |                                               |
      | id                                   | 89015cc9-bdf1-458a-8518-fdca2b4a5785          |
      | image                                | cirros (397e713c-b95b-4186-ad46-6126863ea0a9) |
      | key_name                             | KeyPair01                                     |
      | name                                 | myCirrosServer                                |
      | os-extended-volumes:volumes_attached | []                                            |
      | progress                             | 0                                             |
      | project_id                           | 5669caad86a04256994cdf755df4d3c1              |
      | properties                           |                                               |
      | security_groups                      | [{u'name': u'default'}]                       |
      | status                               | BUILD                                         |
      | updated                              | 2016-11-30T14:48:05Z                          |
      | user_id                              | c36cec73b0e44876a4478b1e6cd749bb              |
      | metadata                             | {u'KEY': u'VALUE'}                            |
      +--------------------------------------+-----------------------------------------------+

   A status of ``BUILD`` indicates that the instance has started, but is
   not yet online.

   A status of ``ACTIVE`` indicates that the instance is active.

#. Copy the server ID value from the ``id`` field in the output. Use the
   ID to get server details or to delete your server.

#. Copy the administrative password value from the ``adminPass`` field. Use the
   password to log in to your server.

#. Check if the instance is online.

   .. code-block:: console

      $ openstack server list

   The list shows the ID, name, status, and private (and if assigned,
   public) IP addresses for all instances in the project to which you
   belong:

   .. code-block:: console

      +-------------+----------------------+--------+------------+-------------+------------------+------------+
      | ID          | Name                 | Status | Task State | Power State | Networks         | Image Name |
      +-------------+----------------------+--------+------------+-------------+------------------+------------+
      | 84c6e57d... | myCirrosServer       | ACTIVE | None       | Running     | private=10.0.0.3 | cirros     |
      | 8a99547e... | myInstanceFromVolume | ACTIVE | None       | Running     | private=10.0.0.4 | centos     |
      +-------------+----------------------+--------+------------+-------------+------------------+------------+

   If the status for the instance is ACTIVE, the instance is online.

#. To view the available options for the :command:`openstack server list`
   command, run the following command:

   .. code-block:: console

      $ openstack help server list

   .. note::

      If you did not provide a key pair, security groups, or rules, you
      can access the instance only from inside the cloud through VNC. Even
      pinging the instance is not possible.

