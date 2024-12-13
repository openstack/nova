=============
Manage shares
=============

Overview
--------

With the Manila share attachment feature, users can easily attach file
shares provided by Manila to their instances, and mount them within the
instance. This feature eliminates the need for users to manually connect
to and mount shares provided by Manila within their instances.

Use Cases
---------

The Manila share attachment feature can be used in the following scenarios:

* As an operator I want the Manila datapath to be separate to any tenant
  accessible networks.

* As a user I want to attach Manila shares directly to my instance and have a
  simple interface with which to mount them within the instance.

  As a user I want to detach a directly attached Manila share from my instance.

* As a user I want to track the Manila shares attached to my instance.

Prerequisites
-------------

To use the Manila share attachment feature, you must have an OpenStack
environment with Manila and Nova installed and configured. Additionally,
your environment must meet the following requirements:

* The compute host running your instance must have ``QEMU`` version 5.0 or
  higher and ``libvirt`` version 6.2 or higher. If these requirements are
  met, the ``COMPUTE_STORAGE_VIRTIO_FS`` trait should be enabled on your
  compute host.
* All compute nodes must be upgraded to a nova version that enables the use of
  virtiofs.
* Additionally this initial implementation will require that the associated
  instances use `file backed memory`__ or `huge pages`__. This is a requirement
  of `virtio-fs`__.
* Kernel drivers and user land tools to support mounting NFS and CEPHFS shares.
* A kernel version of >= 5.4 within the instance guest OS to support mounting
  virtiofs shares.

.. __: https://docs.openstack.org/nova/latest/admin/file-backed-memory.html
.. __: https://docs.openstack.org/nova/latest/admin/huge-pages.html
.. __: https://virtio-fs.gitlab.io/

Configure instance shared memory
--------------------------------

This can be achieved by either configuring the instance with
``hw:mem_page_size`` extra spec.

or, you can enable the ``COMPUTE_MEM_BACKING_FILE`` trait by configuring
the file_backed_memory feature in ``libvirt`` for nova-compute. This will
allow the use of file-backed memory.

``COMPUTE_MEM_BACKING_FILE`` support requires that operators configure one or
more hosts with file backed memory. Ensuring the instance will land on one of
these hosts can be achieved by creating an AZ englobing these hosts.
And then instruct users to deploy their instances in this AZ.
Alternatively, operators can guide the scheduler to choose a suitable host
by adding ``trait:COMPUTE_MEM_BACKING_FILE=required`` as an extra spec or
image property.

Limitations
-----------
* You must have an instance in the SHUTOFF state to attach or detach a share.
* Due to current virtiofs implementation in Qemu / libvirt, the following
  Nova features are blocked for VMs with shares attached:

  * evacuate
  * live_migrate
  * rebuild
  * resize(migrate)
  * resume
  * shelve
  * volume snapshot

Known bugs
----------
* Due to a `bug`__, the configuration drive is not refreshed at the appropriate
  time, causing the shares to remain invisible on the configuration drive.
  You can use the metadata service instead.

* The share backup process removes share access and locks because it requires
  exclusive access for backup consistency.  This operation `disrupts`__
  the share attachment, making it inaccessible for the VM.

  To use this feature correctly, follow these steps:

  1. Stop the VM.
  2. Detach the share from the VM (Nova removes the lock).
  3. Perform the backup using the Manila API.
  4. Reattach the share (Nova reapplies the lock).
  5. Start the VM.

* Nova `does not send the user's token alongside Nova's service
  token`__, Manila will only recognize Nova as the requester during access
  creation.
  Consequently, the audit trail log will lack information indicating
  that Nova is acting on behalf of a user request. This is a significant
  limitation of the current implementation.

* The share is `not marked as an error`__ if the VM fails to delete.

.. __: https://bugs.launchpad.net/nova/+bug/2088464
.. __: https://bugs.launchpad.net/nova/+bug/2089007
.. __: https://bugs.launchpad.net/nova/+bug/2089030
.. __: https://bugs.launchpad.net/nova/+bug/2089034

Managing shares
---------------

Attaching a Share
~~~~~~~~~~~~~~~~~

To attach a Manila share to an instance, use the ``POST
/servers/{server_id}/shares API``, and specify the ``share_id`` of the
share you want to attach. The tag parameter is optional and can be used
to provide a string used to mount the share within the instance. If you do
not provide a tag, the share_id will be used instead.

After issuing the attach request, the share's attachment state is recorded
in the database and should quickly transition to attaching and then to
inactive. The user should verify that the status reaches inactive before
proceeding with any new operations; this transition should occur unless an
error arises.

.. code-block:: shell

  $ openstack server add share 9736bced-44f6-48fc-b913-f34c3ed95067 3d3aafde-b4cb-45ab-8ac6-31ff93f69536 --tag mytag
  +-----------------+--------------------------------------------------------------------------------------+
  | Field           | Value                                                                                |
  +-----------------+--------------------------------------------------------------------------------------+
  | Export Location | 192.168.122.76:/opt/stack/data/manila/mnt/share-25a777f7-a582-465c-a94c-7293707cc5cb |
  | Share ID        | 3d3aafde-b4cb-45ab-8ac6-31ff93f69536                                                 |
  | Status          | inactive                                                                             |
  | Tag             | mytag                                                                                |
  | UUID            | b70403ee-f598-4552-b9e9-173343deff79                                                 |
  +-----------------+--------------------------------------------------------------------------------------+

Then, when you power on the instance, the required operations will be done
to attach the share, and set it as active if there are no errors.
If the attach operation fails, the VM start operation will also fail.

.. code-block:: shell

  $ openstack server share show  9736bced-44f6-48fc-b913-f34c3ed95067 3d3aafde-b4cb-45ab-8ac6-31ff93f69536
  +-----------------+--------------------------------------------------------------------------------------+
  | Field           | Value                                                                                |
  +-----------------+--------------------------------------------------------------------------------------+
  | Export Location | 192.168.122.76:/opt/stack/data/manila/mnt/share-25a777f7-a582-465c-a94c-7293707cc5cb |
  | Share ID        | 3d3aafde-b4cb-45ab-8ac6-31ff93f69536                                                 |
  | Status          | active                                                                               |
  | Tag             | mytag                                                                                |
  | UUID            | b70403ee-f598-4552-b9e9-173343deff79                                                 |
  +-----------------+--------------------------------------------------------------------------------------+

After connecting to the VM, you can retrieve the tags of the attached share
by querying the OpenStack metadata service.

Note: Here, we can see 2 shares attached to the instance with a defined
tag (mytag) and another one with the default tag.

Note2: Using this mechanism, shares can be easily mounted automatically
when the machine starts up.

.. code-block:: shell

  $ curl -s -H "Metadata-Flavor: OpenStack" http://169.254.169.254/openstack/latest/meta_data.json | jq .devices
  [
    {
      "type": "share",
      "share_id": "3d3aafde-b4cb-45ab-8ac6-31ff93f69536",
      "tag": "mytag",
      "bus": "none",
      "address": "none"
    },
    {
      "type": "share",
      "share_id": "894a530c-6fa0-4aa1-97c9-4489d205c5ed",
      "tag": "894a530c-6fa0-4aa1-97c9-4489d205c5ed",
      "bus": "none",
      "address": "none"
    }
  ]

To mount the attached share, use the mount command with the virtiofs file
system type, and the tag provided in the response body.

.. code-block:: shell

    user@instance $ mount -t virtiofs $tag /mnt/mount/path

Detaching a Share
~~~~~~~~~~~~~~~~~
To detach a Manila share, first stop the instance, then use the ``DELETE
/servers/{server_id}/shares/{share_id}`` API, specifying the share_id of
the share you wish to detach.

.. code-block:: shell

  $ openstack server remove share 9736bced-44f6-48fc-b913-f34c3ed95067 3d3aafde-b4cb-45ab-8ac6-31ff93f69536

Listing Attached Shares
~~~~~~~~~~~~~~~~~~~~~~~

To list all shares attached to an instance, use the ``GET
/servers/{server_id}/shares`` API.

.. code-block:: shell

  $ openstack server share list 9736bced-44f6-48fc-b913-f34c3ed95067
  +--------------------------------------+----------+--------------------------------------+
  | Share ID                             | Status   | Tag                                  |
  +--------------------------------------+----------+--------------------------------------+
  | 3d3aafde-b4cb-45ab-8ac6-31ff93f69536 | inactive | mytag                                |
  | 894a530c-6fa0-4aa1-97c9-4489d205c5ed | inactive | 894a530c-6fa0-4aa1-97c9-4489d205c5ed |
  | 9238fc76-5b21-4b8e-80ef-26d74d192f71 | inactive | 9238fc76-5b21-4b8e-80ef-26d74d192f71 |
  +--------------------------------------+----------+--------------------------------------+

Showing Details of an Attached Share
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To show the details of a specific share attached to an instance, use the
``GET /servers/{server_id}/shares/{share_id}`` API, and specify the
``share_id`` of the share you want to show.

.. code-block:: shell


  $ openstack server share show 9736bced-44f6-48fc-b913-f34c3ed95067 3d3aafde-b4cb-45ab-8ac6-31ff93f69536
  +-----------------+--------------------------------------------------------------------------------------+
  | Field           | Value                                                                                |
  +-----------------+--------------------------------------------------------------------------------------+
  | Export Location | 192.168.122.76:/opt/stack/data/manila/mnt/share-25a777f7-a582-465c-a94c-7293707cc5cb |
  | Share ID        | 3d3aafde-b4cb-45ab-8ac6-31ff93f69536                                                 |
  | Status          | inactive                                                                             |
  | Tag             | mytag                                                                                |
  | UUID            | 8a8b42f4-7cd5-49f2-b89c-f27b2ed89cd5                                                 |
  +-----------------+--------------------------------------------------------------------------------------+

Notification of Share Attachment and Detachment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

New notifications will be added for share attach and share detach. You can
enable them using ``include_share_mapping`` configuration parameter. Then you
can subscribe to these notifications to receive information about share
attachment and detachment events.

Available versioned notifications:
https://docs.openstack.org/nova/latest/reference/notifications.html
