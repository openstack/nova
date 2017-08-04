==================
Evacuate instances
==================

If a hardware malfunction or other error causes a cloud compute node to fail,
you can evacuate instances to make them available again. You can optionally
include the target host on the :command:`nova evacuate` command. If you omit
the host, the scheduler chooses the target host.

To preserve user data on the server disk, configure shared storage on the
target host. When you evacuate the instance, Compute detects whether shared
storage is available on the target host. Also, you must validate that the
current VM host is not operational. Otherwise, the evacuation fails.

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

#. To preserve the user disk data on the evacuated server, deploy Compute with
   a shared file system. To configure your system, see
   :ref:`section_configuring-compute-migrations`.  The following example does
   not change the password.

   .. code-block:: console

      $ nova evacuate EVACUATED_SERVER_NAME HOST_B --on-shared-storage
