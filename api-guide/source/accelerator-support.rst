==============================
Using accelerators with Cyborg
==============================

Starting from microversion 2.82, nova supports creating servers with
accelerators provisioned with the Cyborg service, which provides lifecycle
management for accelerators.

To launch servers with accelerators, the administrator (or an user with
appropriate privileges) must do the following:

  * Create a device profile in Cyborg, which specifies what accelerator
    resources need to be provisioned. (See `Cyborg device profiles API
    <https://docs.openstack.org/api-ref/accelerator/v2/index.html#device-profiles>`_.

  * Set the device profile name as an extra spec in a chosen flavor,
    with this syntax:

    .. code::

       accel:device_profile=$device_profile_name

   The chosen flavor may be a newly created one or an existing one.

  * Use that flavor to create a server:

    .. code::

       openstack server create --flavor $myflavor --image $myimage $servername

As of 21.0.0 (Ussuri), nova supports only specific operations for instances
with accelerators. The lists of supported and unsupported operations are as
below:

  * Supported operations.

    * Creation and deletion.
    * Reboots (soft and hard).
    * Pause and unpause.
    * Stop and start.
    * Take a snapshot.
    * Backup.
    * Rescue and unrescue.

  * Unsupported operations

    * Rebuild.
    * Resize.
    * Evacuate.
    * Suspend and resume.
    * Shelve and unshelve.
    * Cold migration.
    * Live migration.

Some operations, such as lock and unlock, work as they are effectively
no-ops for accelerators.
