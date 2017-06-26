====================
Troubleshoot Compute
====================

Common problems for Compute typically involve misconfigured networking or
credentials that are not sourced properly in the environment. Also, most flat
networking configurations do not enable :command:`ping` or :command:`ssh` from
a compute node to the instances that run on that node. Another common problem
is trying to run 32-bit images on a 64-bit compute node.  This section shows
you how to troubleshoot Compute.

Compute service logging
~~~~~~~~~~~~~~~~~~~~~~~

Compute stores a log file for each service in ``/var/log/nova``. For example,
``nova-compute.log`` is the log for the ``nova-compute`` service. You can set
the following options to format log strings for the ``nova.log`` module in the
``nova.conf`` file:

* ``logging_context_format_string``

* ``logging_default_format_string``

If the log level is set to ``debug``, you can also specify
``logging_debug_format_suffix`` to append extra formatting.  For information
about what variables are available for the formatter, see `Formatter Objects
<https://docs.python.org/library/logging.html#formatter-objects>`_.

You have two logging options for OpenStack Compute based on configuration
settings. In ``nova.conf``, include the ``logfile`` option to enable logging.
Alternatively you can set ``use_syslog = 1`` so that the nova daemon logs to
syslog.

Guru Meditation reports
~~~~~~~~~~~~~~~~~~~~~~~

A Guru Meditation report is sent by the Compute service upon receipt of the
``SIGUSR2`` signal (``SIGUSR1`` before Mitaka). This report is a
general-purpose error report that includes details about the current state of
the service. The error report is sent to ``stderr``.

For example, if you redirect error output to ``nova-api-err.log`` using
:command:`nova-api 2>/var/log/nova/nova-api-err.log`, resulting in the process
ID 8675, you can then run:

.. code-block:: console

   # kill -USR2 8675

This command triggers the Guru Meditation report to be printed to
``/var/log/nova/nova-api-err.log``.

The report has the following sections:

* Package: Displays information about the package to which the process belongs,
  including version information.

* Threads: Displays stack traces and thread IDs for each of the threads within
  the process.

* Green Threads: Displays stack traces for each of the green threads within the
  process (green threads do not have thread IDs).

* Configuration: Lists all configuration options currently accessible through
  the CONF object for the current process.

For more information, see `Guru Meditation Reports
<https://docs.openstack.org/developer/nova/devref/gmr.html>`_.

.. _compute-common-errors-and-fixes:

Common errors and fixes for Compute
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The `ask.openstack.org <http://ask.openstack.org>`_ site offers a place to ask
and answer questions, and you can also mark questions as frequently asked
questions. This section describes some errors people have posted previously.
Bugs are constantly being fixed, so online resources are a great way to get the
most up-to-date errors and fixes.

Credential errors, 401, and 403 forbidden errors
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Problem
-------

Missing credentials cause a ``403 forbidden`` error.

Solution
--------

To resolve this issue, use one of these methods:

#. Manual method

   Gets the ``novarc`` file from the project ZIP file, saves existing
   credentials in case of override, and manually sources the ``novarc`` file.

#. Script method

   Generates ``novarc`` from the project ZIP file and sources it for you.

When you run ``nova-api`` the first time, it generates the certificate
authority information, including ``openssl.cnf``. If you start the CA services
before this, you might not be able to create your ZIP file. Restart the
services.  When your CA information is available, create your ZIP file.

Also, check your HTTP proxy settings to see whether they cause problems with
``novarc`` creation.

Instance errors
~~~~~~~~~~~~~~~

Problem
-------

Sometimes a particular instance shows ``pending`` or you cannot SSH to it.
Sometimes the image itself is the problem. For example, when you use flat
manager networking, you do not have a DHCP server and certain images do not
support interface injection; you cannot connect to them.

Solution
--------

To fix instance errors use an image that does support this method, such as
Ubuntu, which obtains an IP address correctly with FlatManager network
settings.

To troubleshoot other possible problems with an instance, such as an instance
that stays in a spawning state, check the directory for the particular instance
under ``/var/lib/nova/instances`` on the ``nova-compute`` host and make sure
that these files are present:

* ``libvirt.xml``
* ``disk``
* ``disk-raw``
* ``kernel``
* ``ramdisk``
* ``console.log``, after the instance starts.

If any files are missing, empty, or very small, the ``nova-compute`` service
did not successfully download the images from the Image service.

Also check ``nova-compute.log`` for exceptions. Sometimes they do not appear in
the console output.

Next, check the log file for the instance in the ``/var/log/libvirt/qemu``
directory to see if it exists and has any useful error messages in it.

Finally, from the ``/var/lib/nova/instances`` directory for the instance, see
if this command returns an error:

.. code-block:: console

   # virsh create libvirt.xml

Empty log output for Linux instances
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Problem
-------

You can view the log output of running instances from either the
:guilabel:`Log` tab of the dashboard or the output of :command:`nova
console-log`. In some cases, the log output of a running Linux instance will be
empty or only display a single character (for example, the `?` character).

This occurs when the Compute service attempts to retrieve the log output of the
instance via a serial console while the instance itself is not configured to
send output to the console.

Solution
--------

To rectify this, append the following parameters to kernel arguments specified
in the instance's boot loader:

.. code-block:: ini

   console=tty0 console=ttyS0,115200n8

Upon rebooting, the instance will be configured to send output to the Compute
service.

Reset the state of an instance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Problem
-------

Instances can remain in an intermediate state, such as ``deleting``.

Solution
--------

You can use the :command:`nova reset-state` command to manually reset the state
of an instance to an error state. You can then delete the instance. For
example:

.. code-block:: console

   $ nova reset-state c6bbbf26-b40a-47e7-8d5c-eb17bf65c485
   $ openstack server delete c6bbbf26-b40a-47e7-8d5c-eb17bf65c485

You can also use the ``--active`` parameter to force the instance back to an
active state instead of an error state. For example:

.. code-block:: console

   $ nova reset-state --active c6bbbf26-b40a-47e7-8d5c-eb17bf65c485

Injection problems
~~~~~~~~~~~~~~~~~~

Problem
-------

Instances may boot slowly, or do not boot. File injection can cause this
problem.

Solution
--------

To disable injection in libvirt, set the following in ``nova.conf``:

.. code-block:: ini

   [libvirt]
   inject_partition = -2

.. note::

   If you have not enabled the configuration drive and you want to make
   user-specified files available from the metadata server for to improve
   performance and avoid boot failure if injection fails, you must disable
   injection.

Disable live snapshotting
~~~~~~~~~~~~~~~~~~~~~~~~~

Problem
-------

Administrators using libvirt version ``1.2.2`` may experience problems with
live snapshot creation. Occasionally, libvirt version ``1.2.2`` fails to create
live snapshots under the load of creating concurrent snapshot.

Solution
--------

To effectively disable the libvirt live snapshotting, until the problem is
resolved, configure the ``disable_libvirt_livesnapshot`` option.  You can turn
off the live snapshotting mechanism by setting up its value to ``True`` in the
``[workarounds]`` section of the ``nova.conf`` file:

.. code-block:: ini

   [workarounds]
   disable_libvirt_livesnapshot = True
