.. _cli-os-migrate-cfg-ssh:

===================================
Configure SSH between compute nodes
===================================

.. todo::

    Consider merging this into a larger "migration" document or to the
    installation guide

If you are resizing or migrating an instance between hypervisors, you might
encounter an SSH (Permission denied) error. Ensure that each node is configured
with SSH key authentication so that the Compute service can use SSH to move
disks to other nodes.

.. note::

   It is not necessary that all the compute nodes share the same key pair.
   However for the ease of the configuration, this document only utilizes a
   single key pair for communication between compute nodes.

To share a key pair between compute nodes, complete the following steps:

#. On the first node, obtain a key pair (public key and private key). Use the
   root key that is in the ``/root/.ssh/id_rsa`` and ``/root/.ssh/id_rsa.pub``
   directories or generate a new key pair.

#. Run :command:`setenforce 0` to put SELinux into permissive mode.

#. Enable login abilities for the nova user:

   .. code-block:: console

      # usermod -s /bin/bash nova

   Ensure you can switch to the nova account:

   .. code-block:: console

      # su - nova

#. As root, create the folder that is needed by SSH and place the private key
   that you obtained in step 1 into this folder, and add the pub key to the
   authorized_keys file:

   .. code-block:: console

      mkdir -p /var/lib/nova/.ssh
      cp <private key>  /var/lib/nova/.ssh/id_rsa
      echo 'StrictHostKeyChecking no' >> /var/lib/nova/.ssh/config
      chmod 600 /var/lib/nova/.ssh/id_rsa /var/lib/nova/.ssh/authorized_keys
      echo <pub key> >> /var/lib/nova/.ssh/authorized_keys

#. Copy the whole folder created in step 4 to the rest of the nodes:

   .. code-block:: console

      # scp -r /var/lib/nova/.ssh remote-host:/var/lib/nova/

#. Ensure that the nova user can now log in to each node without using a
   password:

   .. code-block:: console

      # su - nova
      $ ssh *computeNodeAddress*
      $ exit

#. As root on each node, restart both libvirt and the Compute services:

   .. code-block:: console

      # systemctl restart libvirtd.service
      # systemctl restart openstack-nova-compute.service
