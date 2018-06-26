==================
Evacuate instances
==================

If a hardware malfunction or other error causes a cloud compute node to fail,
you can evacuate instances to make them available again.

To preserve user data on the server disk, configure shared storage on the
target host. When you evacuate the instance, Compute detects whether shared
storage is available on the target host. Also, you must validate that the
current VM host is not operational. Otherwise, the evacuation fails.

There are two different ways to evacuate instances from a failed compute
node. The first one using the :command:`nova evacuate` command can be used to
evacuate a single instance from a failed node. In some cases where the node
in question hosted many instances it might be easier to use
:command:`nova host-evacuate` to evacuate them all in one shot.

Evacuate a single instance
~~~~~~~~~~~~~~~~~~~~~~~~~~

The procedure below explains how to evacuate a single instance from a failed
compute node. Please be aware that these steps describe a post failure
scenario and should not be used if the instance is still up and running.

#. To find a host for the evacuated instance, list all hosts:

   .. code-block:: console

      $ openstack host list

#. Evacuate the instance. You can use the ``--password PWD`` option to pass the
   instance password to the command. If you do not specify a password, the
   command generates and prints one after it finishes successfully. The
   following command evacuates a server from a failed host to ``HOST_B``.

   .. code-block:: console

      $ nova evacuate EVACUATED_SERVER_NAME HOST_B

   The command rebuilds the instance from the original image or volume and
   returns a password. The command preserves the original configuration, which
   includes the instance ID, name, uid, IP address, and so on.

   .. code-block:: console

      +-----------+--------------+
      | Property  |    Value     |
      +-----------+--------------+
      | adminPass | kRAJpErnT4xZ |
      +-----------+--------------+

   Optionally you can omit the ``HOST_B`` parameter and let the scheduler
   choose a new target host.

#. To preserve the user disk data on the evacuated server, deploy Compute with
   a shared file system. To configure your system, see
   :ref:`section_configuring-compute-migrations`.  The following example does
   not change the password.

   .. code-block:: console

      $ nova evacuate EVACUATED_SERVER_NAME HOST_B --on-shared-storage

   .. note:: Starting with the 2.14 compute API version, one no longer needs
             to specify ``--on-shared-storage`` even if the server is on a
             compute host which is using shared storage. The compute service
             will automatically detect if it is running on shared storage.

Evacuate all instances
~~~~~~~~~~~~~~~~~~~~~~

The procedure below explains how to evacuate all instances from a failed compute
node. Please note that this method should not be used if the host still has
instances up and running.

#. To find a host for the evacuated instances, list all hosts:

   .. code-block:: console

      $ openstack host list


#. Evacuate all instances from ``FAILED_HOST`` to ``TARGET_HOST``:

   .. code-block:: console

      $ nova host-evacuate --target_host TARGET_HOST FAILED_HOST

   The option ``--target_host`` is optional and can be omitted to let the
   scheduler decide where to place the instances.

   The above argument ``FAILED_HOST`` can also be a pattern
   to search for instead of an exact hypervisor hostname but it is
   recommended to use a fully qualified domain name to make sure no
   hypervisor host is getting evacuated by mistake. As long as you are not
   using a pattern you might want to use the ``--strict`` flag which got introduced
   in version 10.2.0 to make sure nova matches the ``FAILED_HOST``
   exactly.
