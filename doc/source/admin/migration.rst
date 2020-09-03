=================
Migrate instances
=================

.. note::

   This documentation is about cold migration. For live migration usage, see
   :doc:`live-migration-usage`.

When you want to move an instance from one compute host to another, you can
migrate the instance. The migration operation, which is also known as the cold
migration operation to distinguish it from the live migration operation,
functions similarly to :doc:`the resize operation </user/resize>` with the main
difference being that a cold migration does not change the flavor of the
instance. As with resize, the scheduler chooses the destination compute host
based on its settings. This process does not assume that the instance has shared
storage available on the target host. If you are using SSH tunneling, you must
ensure that each node is configured with SSH key authentication so that the
Compute service can use SSH to move disks to other nodes. For more information,
see :ref:`cli-os-migrate-cfg-ssh`.

To list the VMs you want to migrate, run:

.. code-block:: console

   $ openstack server list

Once you have the name or UUID of the server you wish to migrate, migrate it
using the :command:`openstack server migrate` command:

.. code-block:: console

   $ openstack server migrate SERVER

Once an instance has successfully migrated, you can use the :command:`openstack
server migrate confirm` command to confirm it:

.. code-block:: console

   $ openstack server migrate confirm SERVER

Alternatively, you can use the :command:`openstack server migrate revert`
command to revert the migration and restore the instance to its previous host:

.. code-block:: console

   $ openstack server migrate revert SERVER

.. note::

   You can configure automatic confirmation of migrations and resizes. Refer to
   the :oslo.config:option:`resize_confirm_window` option for more information.


Example
-------

To migrate an instance and watch the status, use this example script:

.. code-block:: bash

   #!/bin/bash

   # Provide usage
   usage() {
       echo "Usage: $0 VM_ID"
       exit 1
   }

   [[ $# -eq 0 ]] && usage
   VM_ID=$1

   # Show the details for the VM
   echo "Instance details:"
   openstack server show ${VM_ID}

   # Migrate the VM to an alternate hypervisor
   echo -n "Migrating instance to alternate host "
   openstack server migrate ${VM_ID}
   while [[ "$(openstack server show ${VM_ID} -f value -c status)" != "VERIFY_RESIZE" ]]; do
       echo -n "."
       sleep 2
   done
   openstack server migrate confirm ${VM_ID}
   echo " instance migrated and resized."

   # Show the details for the migrated VM
   echo "Migrated instance details:"
   openstack server show ${VM_ID}

   # Pause to allow users to examine VM details
   read -p "Pausing, press <enter> to exit."

.. note::

   If you see the following error, it means you are either running the command
   with the wrong credentials, such as a non-admin user, or the ``policy.yaml``
   file prevents migration for your user::

     Policy doesn't allow os_compute_api:os-migrate-server:migrate to be performed. (HTTP 403)

.. note::

   If you see the following error, similar to this message, SSH tunneling was
   not set up between the compute nodes::

     ProcessExecutionError: Unexpected error while running command.
     Stderr: u Host key verification failed.\r\n

The instance is booted from a new host, but preserves its configuration
including instance ID, name, IP address, any metadata, and other properties.
