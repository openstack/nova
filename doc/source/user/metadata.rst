========
Metadata
========

Nova presents configuration information to instances it starts via a mechanism
called metadata. These mechanisms are widely used via helpers such as
`cloud-init`_ to specify things like the root password the instance should use.

This metadata is made available via either a *config drive* or the *metadata
service* and can be somewhat customised by the user using the *user data*
feature. This guide provides an overview of these features along with a summary
of the types of metadata available.

.. _cloud-init: https://cloudinit.readthedocs.io/en/latest/


Types of metadata
-----------------

There are three separate groups of users who need to be able to specify
metadata for an instance.

User provided data
~~~~~~~~~~~~~~~~~~

The user who booted the instance can pass metadata to the instance in several
ways. For authentication keypairs, the keypairs functionality of the nova API
can be used to upload a key and then specify that key during the nova boot API
request. For less structured data, a small opaque blob of data may be passed
via the :ref:`user data <metadata-userdata>` feature of the nova API. Examples
of such unstructured data would be the puppet role that the instance should use,
or the HTTP address of a server from which to fetch post-boot configuration
information.

Nova provided data
~~~~~~~~~~~~~~~~~~

Nova itself needs to pass information to the instance via its internal
implementation of the metadata system. Such information includes the requested
hostname for the instance and the availability zone the instance is in. This
happens by default and requires no configuration by the user or deployer.

Nova provides both an :ref:`OpenStack metadata API <metadata-openstack-format>`
and an :ref:`EC2-compatible API <metadata-ec2-format>`. Both the OpenStack
metadata and EC2-compatible APIs are versioned by date. These are described
later.

Deployer provided data
~~~~~~~~~~~~~~~~~~~~~~

A deployer of OpenStack may need to pass data to an instance. It is also
possible that this data is not known to the user starting the instance. An
example might be a cryptographic token to be used to register the instance with
Active Directory post boot -- the user starting the instance should not have
access to Active Directory to create this token, but the nova deployment might
have permissions to generate the token on the user's behalf. This is possible
using the :ref:`vendordata <metadata-vendordata>` feature, which must be
configured by your cloud operator.



.. _metadata-service:

The metadata service
--------------------

.. note::

    This section provides end user information about the metadata service. For
    deployment information about the metadata service, refer to the :doc:`admin
    guide </admin/metadata-service>`.

The *metadata service* provides a way for instances to retrieve
instance-specific data via a REST API. Instances access this service at
``169.254.169.254`` and all types of metadata, be it user-, nova- or
vendor-provided, can be accessed via this service.

Using the metadata service
~~~~~~~~~~~~~~~~~~~~~~~~~~

To retrieve a list of supported versions for the :ref:`OpenStack metadata API
<metadata-openstack-format>`, make a GET request to
``http://169.254.169.254/openstack``, which will return a list of directories:

.. code-block:: console

   $ curl http://169.254.169.254/openstack
   2012-08-10
   2013-04-04
   2013-10-17
   2015-10-15
   2016-06-30
   2016-10-06
   2017-02-22
   2018-08-27
   latest

Refer to :ref:`OpenStack format metadata <metadata-openstack-format>` for
information on the contents and structure of these directories.

To list supported versions for the :ref:`EC2-compatible metadata API
<metadata-ec2-format>`, make a GET request to ``http://169.254.169.254``, which
will, once again, return a list of directories:

.. code-block:: console

   $ curl http://169.254.169.254
   1.0
   2007-01-19
   2007-03-01
   2007-08-29
   2007-10-10
   2007-12-15
   2008-02-01
   2008-09-01
   2009-04-04
   latest

Refer to :ref:`EC2-compatible metadata <metadata-ec2-format>` for information on
the contents and structure of these directories.


.. _metadata-config-drive:

Config drives
-------------

.. note::

    This section provides end user information about config drives. For
    deployment information about the config drive feature, refer to the
    :doc:`admin guide </admin/config-drive>`.

*Config drives* are special drives that are attached to an instance when
it boots. The instance can mount this drive and read files from it to get
information that is normally available through the metadata service.

One use case for using the config drive is to pass a networking configuration
when you do not use DHCP to assign IP addresses to instances. For example, you
might pass the IP address configuration for the instance through the config
drive, which the instance can mount and access before you configure the network
settings for the instance.

Using the config drive
~~~~~~~~~~~~~~~~~~~~~~

To enable the config drive for an instance, pass the ``--config-drive true``
parameter to the :command:`openstack server create` command.

The following example enables the config drive and passes a user data file and
two key/value metadata pairs, all of which are accessible from the config
drive:

.. code-block:: console

   $ openstack server create --config-drive true --image my-image-name \
       --flavor 1 --key-name mykey --user-data ./my-user-data.txt \
       --property role=webservers --property essential=false MYINSTANCE

.. note::

    The Compute service can be configured to always create a config drive. For
    more information, refer to :doc:`the admin guide </admin/config-drive>`.

If your guest operating system supports accessing disk by label, you can mount
the config drive as the ``/dev/disk/by-label/configurationDriveVolumeLabel``
device. In the following example, the config drive has the ``config-2`` volume
label:

.. code-block:: console

   # mkdir -p /mnt/config
   # mount /dev/disk/by-label/config-2 /mnt/config

If your guest operating system does not use ``udev``, the ``/dev/disk/by-label``
directory is not present. You can use the :command:`blkid` command to identify
the block device that corresponds to the config drive. For example:

.. code-block:: console

   # blkid -t LABEL="config-2" -odevice
   /dev/vdb

Once identified, you can mount the device:

.. code-block:: console

   # mkdir -p /mnt/config
   # mount /dev/vdb /mnt/config

Once mounted, you can examine the contents of the config drive:

.. code-block:: console

   $ cd /mnt/config
   $ find . -maxdepth 2
   .
   ./ec2
   ./ec2/2009-04-04
   ./ec2/latest
   ./openstack
   ./openstack/2012-08-10
   ./openstack/2013-04-04
   ./openstack/2013-10-17
   ./openstack/2015-10-15
   ./openstack/2016-06-30
   ./openstack/2016-10-06
   ./openstack/2017-02-22
   ./openstack/latest

The files that appear on the config drive depend on the arguments that you pass
to the :command:`openstack server create` command. The format of this directory
is the same as that provided by the :ref:`metadata service <metadata-service>`,
with the exception that the EC2-compatible metadata is now located in the
``ec2`` directory instead of the root (``/``) directory. Refer to the
:ref:`metadata-openstack-format` and :ref:`metadata-ec2-format` sections for
information about the format of the files and subdirectories within these
directories.


Nova metadata
-------------

As noted previously, nova provides its metadata in two formats: OpenStack format
and EC2-compatible format.

.. _metadata-openstack-format:

OpenStack format metadata
~~~~~~~~~~~~~~~~~~~~~~~~~

.. versionchanged:: 12.0.0

    Support for network metadata was added in the Liberty release.

Metadata from the OpenStack API is distributed in JSON format. There are two
files provided for each version: ``meta_data.json`` and ``network_data.json``.
The ``meta_data.json`` file contains nova-specific information, while the
``network_data.json`` file contains information retrieved from neutron. For
example:

.. code-block:: console

   $ curl http://169.254.169.254/openstack/2018-08-27/meta_data.json

.. code-block:: json

   {
      "random_seed": "yu5ZnkqF2CqnDZVAfZgarGLoFubhcK5wHG4fcNfVZEtie/bTV8k2dDXK\
                      C7krP2cjp9A7g9LIWe5+WSaZ3zpvQ03hp/4mMNy9V1U/mnRMZyQ3W4Fn\
                      Nex7UP/0Smjb9rVzfUb2HrVUCN61Yo4jHySTd7UeEasF0nxBrx6NFY6e\
                      KRoELGPPr1S6+ZDcDT1Sp7pRoHqwVbzyJZc80ICndqxGkZOuvwDgVKZD\
                      B6O3kFSLuqOfNRaL8y79gJizw/MHI7YjOxtPMr6g0upIBHFl8Vt1VKjR\
                      s3zB+c3WkC6JsopjcToHeR4tPK0RtdIp6G2Bbls5cblQUAc/zG0a8BAm\
                      p6Pream9XRpaQBDk4iXtjIn8Bf56SCANOFfeI5BgBeTwfdDGoM0Ptml6\
                      BJQiyFtc3APfXVVswrCq2SuJop+spgrpiKXOzXvve+gEWVhyfbigI52e\
                      l1VyMoyZ7/pbdnX0LCGHOdAU8KRnBoo99ZOErv+p7sROEIN4Yywq/U/C\
                      xXtQ5BNCtae389+3yT5ZCV7fYzLYChgDMJSZ9ds9fDFIWKmsRu3N+wUg\
                      eL4klxAjRgzQ7MMlap5kppnIYRxXVy0a5j1qOaBAzJB5LLJ7r3/Om38x\
                      Z4+XGWjqd6KbSwhUVs1aqzxpep1Sp3nTurQCuYjgMchjslt0O5oJjh5Z\
                      hbCZT3YUc8M=\n",
      "uuid": "d8e02d56-2648-49a3-bf97-6be8f1204f38",
      "availability_zone": "nova",
      "keys": [
          {
            "data": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDYVEprvtYJXVOBN0XNKV\
                     VRNCRX6BlnNbI+USLGais1sUWPwtSg7z9K9vhbYAPUZcq8c/s5S9dg5vTH\
                     bsiyPCIDOKyeHba4MUJq8Oh5b2i71/3BISpyxTBH/uZDHdslW2a+SrPDCe\
                     uMMoss9NFhBdKtDkdG9zyi0ibmCP6yMdEX8Q== Generated by Nova\n",
            "type": "ssh",
            "name": "mykey"
          }
      ],
      "hostname": "test.novalocal",
      "launch_index": 0,
      "meta": {
         "priority": "low",
         "role": "webserver"
      },
      "devices": [
          {
            "type": "nic",
            "bus": "pci",
            "address": "0000:00:02.0",
            "mac": "00:11:22:33:44:55",
            "tags": ["trusted"]
          },
          {
            "type": "disk",
            "bus": "ide",
            "address": "0:0",
            "serial": "disk-vol-2352423",
            "path": "/dev/sda",
            "tags": ["baz"]
          }
      ],
      "project_id": "f7ac731cc11f40efbc03a9f9e1d1d21f",
      "public_keys": {
          "mykey": "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDYVEprvtYJXVOBN0XNKV\
                    VRNCRX6BlnNbI+USLGais1sUWPwtSg7z9K9vhbYAPUZcq8c/s5S9dg5vTH\
                    bsiyPCIDOKyeHba4MUJq8Oh5b2i71/3BISpyxTBH/uZDHdslW2a+SrPDCe\
                    uMMoss9NFhBdKtDkdG9zyi0ibmCP6yMdEX8Q== Generated by Nova\n"
      },
      "name": "test"
   }

.. code-block:: console

   $ curl http://169.254.169.254/openstack/2018-08-27/network_data.json

.. code-block:: json

   {
       "links": [
           {
               "ethernet_mac_address": "fa:16:3e:9c:bf:3d",
               "id": "tapcd9f6d46-4a",
               "mtu": null,
               "type": "bridge",
               "vif_id": "cd9f6d46-4a3a-43ab-a466-994af9db96fc"
           }
       ],
       "networks": [
           {
               "id": "network0",
               "link": "tapcd9f6d46-4a",
               "network_id": "99e88329-f20d-4741-9593-25bf07847b16",
               "type": "ipv4_dhcp"
           }
       ],
       "services": [
           {
               "address": "8.8.8.8",
               "type": "dns"
           }
       ]
   }


::download:`Download</../../doc/api_schemas/network_data.json>` network_data.json JSON schema.

.. _metadata-ec2-format:

EC2-compatible metadata
~~~~~~~~~~~~~~~~~~~~~~~

The EC2-compatible API is compatible with version 2009-04-04 of the `Amazon EC2
metadata service`__ This means that virtual machine images designed for EC2 will
work properly with OpenStack.

The EC2 API exposes a separate URL for each metadata element. Retrieve a
listing of these elements by making a GET query to
``http://169.254.169.254/2009-04-04/meta-data/``. For example:

.. code-block:: console

   $ curl http://169.254.169.254/2009-04-04/meta-data/
   ami-id
   ami-launch-index
   ami-manifest-path
   block-device-mapping/
   hostname
   instance-action
   instance-id
   instance-type
   kernel-id
   local-hostname
   local-ipv4
   placement/
   public-hostname
   public-ipv4
   public-keys/
   ramdisk-id
   reservation-id
   security-groups

.. code-block:: console

   $ curl http://169.254.169.254/2009-04-04/meta-data/block-device-mapping/
   ami

.. code-block:: console

   $ curl http://169.254.169.254/2009-04-04/meta-data/placement/
   availability-zone

.. code-block:: console

   $ curl http://169.254.169.254/2009-04-04/meta-data/public-keys/
   0=mykey

Instances can retrieve the public SSH key (identified by keypair name when a
user requests a new instance) by making a GET request to
``http://169.254.169.254/2009-04-04/meta-data/public-keys/0/openssh-key``:

.. code-block:: console

   $ curl http://169.254.169.254/2009-04-04/meta-data/public-keys/0/openssh-key
   ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDYVEprvtYJXVOBN0XNKVVRNCRX6BlnNbI+US\
   LGais1sUWPwtSg7z9K9vhbYAPUZcq8c/s5S9dg5vTHbsiyPCIDOKyeHba4MUJq8Oh5b2i71/3B\
   ISpyxTBH/uZDHdslW2a+SrPDCeuMMoss9NFhBdKtDkdG9zyi0ibmCP6yMdEX8Q== Generated\
   by Nova

__ https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-metadata.html


.. _metadata-userdata:

User data
---------

*User data* is a blob of data that the user can specify when they launch an
instance. The instance can access this data through the metadata service or
config drive. Commonly used to pass a shell script that the instance runs on
boot.

For example, one application that uses user data is the `cloud-init
<https://help.ubuntu.com/community/CloudInit>`__ system, which is an open-source
package from Ubuntu that is available on various Linux distributions and which
handles early initialization of a cloud instance.

You can place user data in a local file and pass it through the ``--user-data
<user-data-file>`` parameter at instance creation.

.. code-block:: console

   $ openstack server create --image ubuntu-cloudimage --flavor 1 \
       --user-data mydata.file VM_INSTANCE

.. note::

    The provided user data should not be base64-encoded, as it will be
    automatically encoded in order to pass valid input to the REST
    API, which has a limit of 65535 bytes after encoding.

Once booted, you can access this data from the instance using either the
metadata service or the config drive. To access it via the metadata service,
make a GET request to either
``http://169.254.169.254/openstack/{version}/user_data`` (OpenStack API) or
``http://169.254.169.254/{version}/user-data`` (EC2-compatible API). For
example:

.. code-block:: console

   $ curl http://169.254.169.254/openstack/2018-08-27/user_data

.. code-block:: shell

   #!/bin/bash
   echo 'Extra user data here'


.. _metadata-vendordata:

Vendordata
----------

.. note::

    This section provides end user information about the vendordata feature. For
    deployment information about this feature, refer to the :doc:`admin guide
    </admin/vendordata>`.

.. versionchanged:: 14.0.0

    Support for dynamic vendor data was added in the Newton release.

**Where configured**, instances can retrieve vendor-specific data from the
metadata service or config drive. To access it via the metadata service, make a
GET request to either
``http://169.254.169.254/openstack/{version}/vendor_data.json`` or
``http://169.254.169.254/openstack/{version}/vendor_data2.json``, depending on
the deployment. For example:

.. code-block:: console

   $ curl http://169.254.169.254/openstack/2018-08-27/vendor_data2.json

.. code-block:: json

   {
       "testing": {
           "value1": 1,
           "value2": 2,
           "value3": "three"
       }
   }

.. note::

    The presence and contents of this file will vary from deployment to
    deployment.


General guidelines
------------------

- Do not rely on the presence of the EC2 metadata in the metadata API or
  config drive, because this content might be removed in a future release. For
  example, do not rely on files in the ``ec2`` directory.

- When you create images that access metadata service or config drive data and
  multiple directories are under the ``openstack`` directory, always select the
  highest API version by date that your consumer supports.  For example, if your
  guest image supports the ``2012-03-05``, ``2012-08-05``, and ``2013-04-13``
  versions, try ``2013-04-13`` first and fall back to a previous version if
  ``2013-04-13`` is not present.
