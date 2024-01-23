===========================
Compute Node Identification
===========================

Nova requires that compute nodes maintain a constant and consistent identity
during their lifecycle. With the exception of the ironic driver, starting in
the 2023.1 release, this is achieved by use of a file containing the node
unique identifier that is persisted on disk. Prior to 2023.1, a combination of
the compute node's hostname and the :oslo.config:option:`host` value in the
configuration file were used.

The 2023.1 and later compute node identification file must remain unchanged
during the lifecycle of the compute node. Changing the value or removing the
file will result in a failure to start and may require advanced techniques
for recovery. The file is read once at ``nova-compute`` startup, at which point
it is validated for formatting and the corresponding node is located or
created in the database.

.. note::

    Even after 2023.1, the compute node's hostname may not be changed after
    the initial registration with the controller nodes, it is just not used
    as the primary method for identification.

The behavior of ``nova-compute`` is different when using the ironic driver,
as the (UUID-based) identity and mapping of compute nodes to compute manager
service hosts is dynamic. In that case, no single node identity is maintained
by the compute host and thus no identity file is read or written. Thus none
of the sections below apply to hosts with :oslo.config:option:`compute_driver`
set to ``ironic``.

Self-provisioning of the node identity
--------------------------------------

By default, ``nova-compute`` will automatically generate and write a UUID to
disk the first time it starts up, and will use that going forward as its
stable identity. Using the :oslo.config:option:`state_path`
(which is ``/var/lib/nova`` on most systems), a ``compute_id`` file will be
created with a generated UUID.

Since this file (and its parent directory) is writable by nova, it may be
desirable to move this to one of the other locations that nova looks for the
identification file.

Deployment provisioning of the node identity
--------------------------------------------

In addition to the location mentioned above, nova will also search the parent
directories of any config file in use (either the defaults or provided on
the command line) for a ``compute_id`` file. Thus, a deployment tool may, on
most systems, pre-provision the node's UUID by writing one to
``/etc/nova/compute_id``.

The contents of the file should be a single UUID in canonical textual
representation with no additional whitespace or other characters. The following
should work on most Linux systems:

.. code-block:: shell

    $ uuidgen > /etc/nova/compute_id

.. note::

    **Do not** execute the above command blindly in every run of a deployment
    tool, as that will result in overwriting the ``compute_id`` file each time,
    which *will* prevent nova from working properly.

Upgrading from pre-2023.1
-------------------------

Before release 2023.1, ``nova-compute`` only used the hostname (combined with
:oslo.config:option:`host`, if set) to identify its compute node objects in
the database. When upgrading from a prior release, the compute node will
perform a one-time migration of the hostname-matched compute node UUID to the
``compute_id`` file in the :oslo.config:option:`state_path` location.

.. note::

    It is imperative that you allow the above migration to run and complete on
    compute nodes that are being upgraded. Skipping this step by
    pre-provisioning a ``compute_id`` file before the upgrade will **not** work
    and will be equivalent to changing the compute node UUID after it has
    already been created once.
