==================================
Use snapshots to migrate instances
==================================

This guide can be used to migrate an instance between different clouds.

To use snapshots to migrate instances from OpenStack projects to clouds,
complete these steps.

In the source project:

#. :ref:`Create_a_snapshot_of_the_instance`

#. :ref:`Download_the_snapshot_as_an_image`

In the destination project:

#. :ref:`Import_the_snapshot_to_the_new_environment`

#. :ref:`Boot_a_new_instance_from_the_snapshot`

.. note::

   Some cloud providers allow only administrators to perform this task.

.. _Create_a_snapshot_of_the_instance:

Create a snapshot of the instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Shut down the source VM before you take the snapshot to ensure that all
   data is flushed to disk. If necessary, list the instances to view the
   instance name:

   .. code-block:: console

      $ openstack server list
      +--------------------------------------+------------+--------+------------------+--------------------+-------------------------+
      | ID                                   | Name       | Status | Networks         | Image              | Flavor                  |
      +--------------------------------------+------------+--------+------------------+--------------------+-------------------------+
      | d0d1b7d9-a6a5-41d3-96ab-07975aadd7fb | myInstance | ACTIVE | private=10.0.0.3 | ubuntu-16.04-amd64 | general.micro.tmp.linux |
      +--------------------------------------+------------+--------+------------------+--------------------+-------------------------+

#. Use the :command:`openstack server stop` command to shut down the instance:

   .. code-block:: console

      $ openstack server stop myInstance

#. Use the :command:`openstack server list` command to confirm that the instance shows a
   ``SHUTOFF`` status:

   .. code-block:: console

      $ openstack server list
      +--------------------------------------+------------+---------+------------------+--------------------+-------------------------+
      | ID                                   | Name       | Status  | Networks         | Image              | Flavor                  |
      +--------------------------------------+------------+---------+------------------+--------------------+-------------------------+
      | d0d1b7d9-a6a5-41d3-96ab-07975aadd7fb | myInstance | SHUTOFF | private=10.0.0.3 | ubuntu-16.04-amd64 | general.micro.tmp.linux |
      +--------------------------------------+------------+---------+------------------+--------------------+-------------------------+

#. Use the :command:`openstack server image create` command to take a snapshot:

   .. code-block:: console

      $ openstack server image create --name myInstanceSnapshot myInstance

   If snapshot operations routinely fail because the user token times out
   while uploading a large disk image, consider configuring nova to use
   :ref:`service user tokens <user_token_timeout>`.

#. Use the :command:`openstack image list` command to check the status
   until the status is ``ACTIVE``:

   .. code-block:: console

      $ openstack image list
      +--------------------------------------+---------------------------+--------+
      | ID                                   | Name                      | Status |
      +--------------------------------------+---------------------------+--------+
      | ab567a44-b670-4d22-8ead-80050dfcd280 | myInstanceSnapshot        | active |
      +--------------------------------------+---------------------------+--------+


.. _Download_the_snapshot_as_an_image:

Download the snapshot as an image
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

#. Get the image ID:

   .. code-block:: console

      $ openstack image list
      +--------------------------------------+---------------------------+--------+
      | ID                                   | Name                      | Status |
      +--------------------------------------+---------------------------+--------+
      | ab567a44-b670-4d22-8ead-80050dfcd280 | myInstanceSnapshot        | active |
      +--------------------------------------+---------------------------+--------+

#. Download the snapshot by using the image ID that was returned in the
   previous step:

   .. code-block:: console

      $ openstack image save --file snapshot.raw ab567a44-b670-4d22-8ead-80050dfcd280

   .. note::

      The :command:`openstack image save` command requires the image ID and
      cannot use the image name.
      Check there is sufficient space on the destination file system for
      the image file.

#. Make the image available to the new environment, either through HTTP or
   direct upload to a machine (``scp``).

.. _Import_the_snapshot_to_the_new_environment:

Import the snapshot to the new environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the new project or cloud environment, import the snapshot:

.. code-block:: console

   $ openstack image create --container-format bare --disk-format qcow2 \
     --file snapshot.raw myInstanceSnapshot

.. _Boot_a_new_instance_from_the_snapshot:

Boot a new instance from the snapshot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In the new project or cloud environment, use the snapshot to create the
new instance:

.. code-block:: console

   $ openstack server create --flavor m1.tiny --image myInstanceSnapshot myNewInstance

