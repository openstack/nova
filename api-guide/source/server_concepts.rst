===============
Server concepts
===============

For the OpenStack Compute API, a server is a virtual machine (VM) instance,
a physical machine or a container.

Server status
~~~~~~~~~~~~~

You can filter the list of servers by image, flavor, name, and status
through the respective query parameters.

Servers contain a status attribute that indicates the current server
state. You can filter on the server status when you complete a list
servers request. The server status is returned in the response body. The
server status is one of the following values:

**Server status values**

-  ``ACTIVE``: The server is active.

-  ``BUILD``: The server has not finished the original build process.

-  ``DELETED``: The server is deleted.

-  ``ERROR``: The server is in error.

-  ``HARD_REBOOT``: The server is hard rebooting. This is equivalent to
   pulling the power plug on a physical server, plugging it back in, and
   rebooting it.

-  ``MIGRATING``: The server is under migrating. This is caused by a
   live migration (moving a server that is active) action.

-  ``PASSWORD``: The password is being reset on the server.

-  ``PAUSED``: The server is paused.

-  ``REBOOT``: The server is in a soft reboot state. A reboot command
   was passed to the operating system.

-  ``REBUILD``: The server is currently being rebuilt from an image.

-  ``RESCUE``: The server is in rescue mode.

-  ``RESIZE``: Server is performing the differential copy of data that
   changed during its initial copy. Server is down for this stage.

-  ``REVERT_RESIZE``: The resize or migration of a server failed for
   some reason. The destination server is being cleaned up and the
   original source server is restarting.

-  ``SHELVED``: The server is in shelved state. Depends on the shelve offload
   time, the server will be automatically shelved off loaded.

-  ``SHELVED_OFFLOADED``: The shelved server is offloaded (removed from the
   compute host) and it needs unshelved action to be used again.

-  ``SHUTOFF``: The virtual machine (VM) was powered down by the user,
   but not through the OpenStack Compute API. For example, the user
   issued a ``shutdown -h`` command from within the server. If
   the OpenStack Compute manager detects that the VM was powered down,
   it transitions the server to the SHUTOFF status. If you use
   the OpenStack Compute API to restart the server, it might
   be deleted first, depending on the value in the
   *``shutdown_terminate``* database field on the Instance model.

-  ``SOFT_DELETED``: The server is marked as deleted while will keep in the
   cloud for some time(configurable), during the period authorized user can
   restore the server back to normal state. When the time expires, the
   server will be deleted permanently.

-  ``SUSPENDED``: The server is suspended, either by request or
   necessity. This status appears for only the following hypervisors:
   XenServer/XCP, KVM, and ESXi. Administrative users may suspend a
   server if it is infrequently used or to perform system maintenance.
   When you suspend a server, its VM state is stored on disk, all
   memory is written to disk, and the virtual machine is stopped.
   Suspending a server is similar to placing a device in hibernation;
   memory and vCPUs become available to create other servers.

-  ``UNKNOWN``: The state of the server is unknown. Contact your cloud
   provider.

-  ``VERIFY_RESIZE``: System is awaiting confirmation that the server is
   operational after a move or resize.

The compute provisioning algorithm has an anti-affinity property that
attempts to spread customer VMs across hosts. Under certain situations,
VMs from the same customer might be placed on the same host. hostId
represents the host your server runs on and can be used to determine
this scenario if it is relevant to your application.

.. note:: HostId is unique *per account* and is not globally unique.

Server creation
~~~~~~~~~~~~~~~

Status Transition:

``BUILD``

``ACTIVE``

``ERROR`` (on error)

When you create a server, the operation asynchronously provisions a new
server. The progress of this operation depends on several factors
including location of the requested image, network I/O, host load, and
the selected flavor. The progress of the request can be checked by
performing a **GET** on /servers/*``id``*, which returns a progress
attribute (from 0% to 100% complete). The full URL to the newly created
server is returned through the ``Location`` header and is available as a
``self`` and ``bookmark`` link in the server representation. Note that
when creating a server, only the server ID, its links, and the
administrative password are guaranteed to be returned in the request.
You can retrieve additional attributes by performing subsequent **GET**
operations on the server.

Server actions
~~~~~~~~~~~~~~~

-  **Reboot**

   Use this function to perform either a soft or hard reboot of a
   server. With a soft reboot, the operating system is signaled to
   restart, which allows for a graceful shutdown of all processes. A
   hard reboot is the equivalent of power cycling the server. The
   virtualization platform should ensure that the reboot action has
   completed successfully even in cases in which the underlying
   domain/VM is paused or halted/stopped.

-  **Rebuild**

   Use this function to remove all data on the server and replaces it
   with the specified image. Server ID and IP addresses remain the same.

-  **Evacuate**

   Should a compute node actually go offline, it can no longer report
   status about any of the servers on it. This means they'll be
   listed in an 'ACTIVE' state forever.

   Evacuate is a work around for this that lets an administrator
   forceably rebuild these zombie servers on another node. It makes
   no guarantees that the host was actually down, so fencing is
   left as an exercise to the deployer.

-  **Resize** (including **Confirm resize**, **Revert resize**)

   Use this function to convert an existing server to a different
   flavor, in essence, scaling the server up or down. The original
   server is saved for a period of time to allow rollback if there is a
   problem. All resizes should be tested and explicitly confirmed, at
   which time the original server is removed. All resizes are
   automatically confirmed after 24 hours if you do not confirm or
   revert them.

   Confirm resize action will delete the old server in the virt layer.
   The spawned server in the virt layer will be used from then on.
   on the contrary, Revert resize action will delete the new server
   spawned in the virt layer and revert all changes, the original server
   will still be used from then on.

   Also, there there is a periodic task configured by param
   CONF.resize_confirm_window(in seconds), if this value is not 0, nova compute
   will check whether the server is in resized state longer than
   CONF.resize_confirm_window, it will automatically confirm the resize
   of the server.

-  **Pause**, **Unpause**

   You can pause a server by making a pause request. This request stores
   the state of the VM in RAM. A paused server continues to run in a
   frozen state.

   Unpause returns a paused server back to an active state.

-  **Suspend**, **Resume**

   Administrative users might want to suspend a server if it is
   infrequently used or to perform system maintenance. When you suspend
   a server, its VM state is stored on disk, all memory is written to
   disk, and the virtual machine is stopped. Suspending a server is
   similar to placing a device in hibernation; memory and vCPUs become
   available to create other servers.

   Resume will resume a suspended server to an active state.

-  **Snapshot**

   You can store the current state of the server root disk to be saved
   and uploaded back into the glance image repository.
   Then the server can later be booted again using this saved image.

-  **Backup**

   You can use backup method to store server's current state in the glance
   repository, in the mean time, old snapshots will be removed based on the
   given 'daily' or 'weekly' type.

-  **Start**

   Power on an server.

-  **Stop**

   Power off an server.

-  **Delete**, **Restore**

   Power off the given server first then detach all the resources associated
   to the server such as network and volumes, then delete the server.

   CONF.reclaim_instance_interval (in seconds) decides whether the server to
   be deleted will still be in the system. If this value is greater than 0,
   the deleted server will not be deleted immediately, instead it will be put
   into a queue until it's too old(deleted time greater than the value of
   CONF.reclaim_instance_interval). Admin is able to use Restore action to
   recover the server from the delete queue. If the deleted server stays
   more than the CONF.reclaim_instance_interval, it will be deleted by compute
   service automatically.

-  **Shelve**, **Shelve offload**, **Unshelve**

   Shelving an server indicates it will not be needed for some time and may be
   temporarily removed from the hypervisors. This allows its resources to
   be freed up for use by someone else.

   Shelve will power off the given server and take a snapshot if it is booted
   from image. The server can then be offloaded from the compute host and its
   resources deallocated. Offloading is done immediately if booted from volume,
   but if booted from image the offload can be delayed for some time or
   indefinitely, leaving the image on disk and the resources still allocated.

   Shelve offload is used to explicitly remove a shelved server that has been
   left on a host. This action can only be used on a shelved server and is
   usually performed by an admin.

   Unshelve is the reverse operation of Shelve. It builds and boots the server
   again, on a new scheduled host if it was offloaded, using the shelved image
   in the glance repository if booted from image.

-  **Lock**, **Unlock**

   Lock a server so no further actions are allowed to the server. This can
   be done by either admin or the server's owner.

   Unlock will unlock an server in locked state so additional
   operations can be performed on the server.

-  **Rescue**, **Unrescue**

   The rescue operation starts a server in a special configuration whereby
   it is booted from a special root disk image. This enables the tenant to try
   and restore a broken vitrual machine.

   Unrescue is the reverse action of Rescue, the server spawned from the special
   root image will be deleted.

-  **Set admin password**

   Set the root/admin password for the given server, it uses an
   optional installed agent to inject the admin password.

-  **Migrate**, **Live migrate**

   Migrate is usually utilized by admin, it will move a server to another
   host; it utilize the 'resize' action but with same flavor, so during
   migration, the server will be power off and rebuilt on another host.

   Live migrate also moves an server from one host to another, but it won't
   power off the server in general so the server will not suffer a down time.
   Administrators may use this to evacuate servers from a host that needs to
   undergo maintenance tasks.

Server passwords
~~~~~~~~~~~~~~~~

You can specify a password when you create the server through the
optional adminPass attribute. The specified password must meet the
complexity requirements set by your OpenStack Compute provider. The
server might enter an ``ERROR`` state if the complexity requirements are
not met. In this case, a client can issue a change password action to
reset the server password.

If a password is not specified, a randomly generated password is
assigned and returned in the response object. This password is
guaranteed to meet the security requirements set by the compute
provider. For security reasons, the password is not returned in
subsequent **GET** calls.

Server metadata
~~~~~~~~~~~~~~~

Custom server metadata can also be supplied at launch time. The maximum
size of the metadata key and value is 255 bytes each. The maximum number
of key-value pairs that can be supplied per server is determined by the
compute provider and may be queried via the maxServerMeta absolute
limit.

Server networks
~~~~~~~~~~~~~~~

Networks to which the server connects can also be supplied at launch
time. One or more networks can be specified. User can also specify a
specific port on the network or the fixed IP address to assign to the
server interface.

Server personality
~~~~~~~~~~~~~~~~~~

You can customize the personality of a server by injecting data
into its file system. For example, you might want to insert ssh keys,
set configuration files, or store data that you want to retrieve from
inside the server. This feature provides a minimal amount of
launch-time personalization. If you require significant customization,
create a custom image.

Follow these guidelines when you inject files:

-  The maximum size of the file path data is 255 bytes.

-  Encode the file contents as a Base64 string. The maximum size of the
   file contents is determined by the compute provider and may vary
   based on the image that is used to create the server

Considerations
~~~~~~~~~~~~~~

   The maximum limit refers to the number of bytes in the decoded data
   and not the number of characters in the encoded data.

-  You can inject text files only. You cannot inject binary or zip files
   into a new build.

-  The maximum number of file path/content pairs that you can supply is
   also determined by the compute provider and is defined by the
   maxPersonality absolute limit.

-  The absolute limit, maxPersonalitySize, is a byte limit that is
   guaranteed to apply to all images in the deployment. Providers can
   set additional per-image personality limits.

The file injection might not occur until after the server is built and
booted.

During file injection, any existing files that match specified files are
renamed to include the BAK extension appended with a time stamp. For
example, if the ``/etc/passwd`` file exists, it is backed up as
``/etc/passwd.bak.1246036261.5785``.

After file injection, personality files are accessible by only system
administrators. For example, on Linux, all files have root and the root
group as the owner and group owner, respectively, and allow user and
group read access only (octal 440).

Server access addresses
~~~~~~~~~~~~~~~~~~~~~~~

In a hybrid environment, the IP address of a server might not be
controlled by the underlying implementation. Instead, the access IP
address might be part of the dedicated hardware; for example, a
router/NAT device. In this case, the addresses provided by the
implementation cannot actually be used to access the server (from
outside the local LAN). Here, a separate *access address* may be
assigned at creation time to provide access to the server. This address
may not be directly bound to a network interface on the server and may
not necessarily appear when a server's addresses are queried.
Nonetheless, clients that must access the server directly are encouraged
to do so via an access address. In the example below, an IPv4 address is
assigned at creation time.


**Example: Create server with access IP: JSON request**

.. code::

    {
       "server":{
          "name":"new-server-test",
          "imageRef":"52415800-8b69-11e0-9b19-734f6f006e54",
          "flavorRef":"52415800-8b69-11e0-9b19-734f1195ff37",
          "accessIPv4":"67.23.10.132"
       }
    }

.. note:: Both IPv4 and IPv6 addresses may be used as access addresses and both
   addresses may be assigned simultaneously as illustrated below. Access
   addresses may be updated after a server has been created.


**Example: Create server with multiple access IPs: JSON request**

.. code::

    {
       "server":{
          "name":"new-server-test",
          "imageRef":"52415800-8b69-11e0-9b19-734f6f006e54",
          "flavorRef":"52415800-8b69-11e0-9b19-734f1195ff37",
          "accessIPv4":"67.23.10.132",
          "accessIPv6":"::babe:67.23.10.132"
       }
    }

Moving servers
~~~~~~~~~~~~~~

There are several actions that may result in a server moving from one
compute host to another including shelve, resize, migrations and
evacuate. The following use cases demonstrate the intention of the
actions and the consequence for operational procedures.

Cloud operator needs to move a server
-------------------------------------

Sometimes a cloud operator may need to redistribute work loads for
operational purposes. For example, the operator may need to remove
a compute host for maintenance or deploy a kernel security patch that
requires the host to be rebooted.

The operator has two actions available for deliberately moving
work loads: cold migration (moving a server that is not active)
and live migration (moving a server that is active).

Cold migration moves a server from one host to another by copying its
state, local storage and network configuration to new resources
allocated on a new host selected by scheduling policies. The operation is
relatively quick as the server is not changing its state during the copy
process. The user does not have access to the server during the operation.

Live migration moves a server from one host to another while it
is active, so it is constantly changing its state during the action.
As a result it can take considerably longer than cold migration.
During the action the server is online and accessible, but only
a limited set of management actions are available to the user.

The following are common patterns for employing migrations in
a cloud:

-  **Host maintenance**

   If a compute host is to be removed from the cloud all its servers
   will need to moved to other hosts. In this case it is normal for
   the rest of the cloud to absorb the work load, redistributing
   the servers by rescheduling them.

   To prepare the host it will be disabled so it does not receive
   any further servers. Then each server will be migrated to a new
   host by cold or live migration, depending on the state of the
   server. When complete, the host is free to be removed.

-  **Rolling updates**

   Often it is necessary to perform an update on all compute hosts
   that requires them to be rebooted. In this case it is not
   strictly necessary to move inactive servers because they
   will be available after the reboot. However, active servers would
   be impacted by the reboot. Live migration will allow them to
   continue operation.

   In this case a rolling approach can be taken by starting with an
   empty compute host that has been updated and rebooted. Another host
   that has not yet been updated is disabled and all its servers are
   migrated to the new host. When the migrations are complete the
   new host continues normal operation. The old host will be empty
   and can be updated and rebooted. It then becomes the new target for
   another round of migrations.

   This process can be repeated until the whole cloud has been updated,
   usually using a pool of empty hosts instead of just one.

- **Resource Optimization**

   To reduce energy usage, some cloud operators will try and move
   servers so they fit into the minimum number of hosts, allowing
   some servers to be turned off.

   Sometimes higher performance might be wanted, so servers are
   spread out between the hosts to minimize resource contention.

Migrating a server is not normally a choice that is available to
the cloud user because the user is not normally aware of compute
hosts. Management of the cloud and how servers are provisioned
in it is the sole responsibility of the cloud operator.

Recover from a failed compute host
----------------------------------

Sometimes a compute host may fail. This is a rare occurrence, but when
it happens during normal operation the servers running on the host may
be lost. In this case the operator may recreate the servers on the
remaining compute hosts using the evacuate action.

Failure detection can be proved to be impossible in compute systems
with asynchronous communication, so true failure detection cannot be
achieved. Usually when a host is considered to have failed it should be
excluded from the cloud and any virtual networking or storage associated
with servers on the failed host should be isolated from it. These steps
are called fencing the host. Initiating these action is outside the scope
of Nova.

Once the host has been fenced its servers can be recreated on other
hosts without worry of the old incarnations reappearing and trying to
access shared resources. It is usual to redistribute the servers
from a failed host by rescheduling them.

Please note, this operation can result in data loss for the user's server.
As there is no access to the original server, if there were any disks stored
on local storage, that data will be lost. Evacuate does the same operation
as a rebuild. It downloads any images from glance and creates new
blank ephemeral disks. Any disks that were volumes, or on shared storage,
are reconnected. There should be no data loss for those disks.
This is why fencing the host is important, to ensure volumes and shared
storage are not corrupted by two servers writing simultaneously.

Evacuating a server is solely in the domain of the cloud operator because
it must be performed in coordination with other operational procedures to
be safe. A user is not normally aware of compute hosts but is adversely
affected by their failure.

User resizes server to get more resources
-----------------------------------------

Sometimes a user may want to change the flavor of a server, e.g. change
the quantity of cpus, disk, memory or any other resource. This is done
by rebuilding the server with a new flavor. As the server is being
moved, it is normal to reschedule the server to another host
(although resize to the same host is an option for the operator).

Resize involves shutting down the server, finding a host that has
the correct resources for the new flavor size, moving the current
server (including all storage) to the new host. Once the server
has been given the appropriate resources to match the new flavor,
the server is started again.

After the resize operation, when the user is happy their server is
working correctly after the resize, the user calls Confirm Resize.
This deletes the backup server that was kept on the source host.
Alternatively, the user can call Revert Resize to delete the new
resized server, and restore the back up that was stored on the source
host. If the user does not manually confirm the resize within a
configured time period, the resize is automatically confirmed, to
free up the space the backup is using on the source host.

As with shelving, resize provides the cloud operator with an
opportunity to redistribute work loads across the cloud according
to the operators scheduling policy, providing the same benefits as
above.

Resizing a server is not normally a choice that is available to
the cloud operator because it changes the nature of the server
being provided to the user.

User doesn't want to be charged when not using a server
-------------------------------------------------------

Sometimes a user does not require a server to be active for a while,
perhaps over a weekend or at certain times of day.
Ideally they don't want to be billed for those resources.
Just powering down a server does not free up any resources,
but shelving a server does free up resources to be used by other users.
This makes it feasible for a cloud operator to offer a discount when
a server is shelved.

When the user shelves a server the operator can choose to remove it
from the compute hosts, i.e. the operator can offload the shelved server.
When the user's server is unshelved, it is scheduled to a new
host according to the operators policies for distributing work loads
across the compute hosts, including taking disabled hosts into account.
This will contribute to increased overall capacity, freeing hosts that
are ear-marked for maintenance and providing contiguous blocks
of resources on single hosts due to moving out old servers.

Shelving a server is not normally a choice that is available to
the cloud operator because it affects the availability of the server
being provided to the user.
