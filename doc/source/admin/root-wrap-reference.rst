====================
Secure with rootwrap
====================

Rootwrap allows unprivileged users to safely run Compute actions as the root
user. Compute previously used :command:`sudo` for this purpose, but this was
difficult to maintain, and did not allow advanced filters. The
:command:`rootwrap` command replaces :command:`sudo` for Compute.

To use rootwrap, prefix the Compute command with :command:`nova-rootwrap`. For
example:

.. code-block:: console

   $ sudo nova-rootwrap /etc/nova/rootwrap.conf command

A generic ``sudoers`` entry lets the Compute user run :command:`nova-rootwrap`
as root. The :command:`nova-rootwrap` code looks for filter definition
directories in its configuration file, and loads command filters from them. It
then checks if the command requested by Compute matches one of those filters
and, if so, executes the command (as root). If no filter matches, it denies the
request.

.. note::

   Be aware of issues with using NFS and root-owned files. The NFS share must
   be configured with the ``no_root_squash`` option enabled, in order for
   rootwrap to work correctly.

Rootwrap is fully controlled by the root user. The root user owns the sudoers
entry which allows Compute to run a specific rootwrap executable as root, and
only with a specific configuration file (which should also be owned by root).
The :command:`nova-rootwrap` command imports the Python modules it needs from a
cleaned, system-default PYTHONPATH.  The root-owned configuration file points
to root-owned filter definition directories, which contain root-owned filters
definition files. This chain ensures that the Compute user itself is not in
control of the configuration or modules used by the :command:`nova-rootwrap`
executable.

Configure rootwrap
~~~~~~~~~~~~~~~~~~

Configure rootwrap in the ``rootwrap.conf`` file. Because it is in the trusted
security path, it must be owned and writable by only the root user. The
``rootwrap_config=entry`` parameter specifies the file's location in the
sudoers entry and in the ``nova.conf`` configuration file.

The ``rootwrap.conf`` file uses an INI file format with these sections and
parameters:

.. list-table:: **rootwrap.conf configuration options**
   :widths: 64 31

   * - Configuration option=Default value
     - (Type) Description
   * - [DEFAULT]
       filters\_path=/etc/nova/rootwrap.d,/usr/share/nova/rootwrap
     - (ListOpt) Comma-separated list of directories
       containing filter definition files.
       Defines where rootwrap filters are stored.
       Directories defined on this line should all
       exist, and be owned and writable only by the
       root user.

If the root wrapper is not performing correctly, you can add a workaround
option into the ``nova.conf`` configuration file. This workaround re-configures
the root wrapper configuration to fall back to running commands as ``sudo``,
and is a Kilo release feature.

Including this workaround in your configuration file safeguards your
environment from issues that can impair root wrapper performance. Tool changes
that have impacted `Python Build Reasonableness (PBR)
<https://opendev.org/openstack/pbr/>`__ for example, are a known
issue that affects root wrapper performance.

To set up this workaround, configure the ``disable_rootwrap`` option in the
``[workaround]`` section of the ``nova.conf`` configuration file.

The filters definition files contain lists of filters that rootwrap will use to
allow or deny a specific command. They are generally suffixed by ``.filters`` .
Since they are in the trusted security path, they need to be owned and writable
only by the root user. Their location is specified in the ``rootwrap.conf``
file.

Filter definition files use an INI file format with a ``[Filters]`` section and
several lines, each with a unique parameter name, which should be different for
each filter you define:

.. list-table:: **Filters configuration options**
   :widths: 72 39


   * - Configuration option=Default value
     - (Type) Description
   * - [Filters]
       filter\_name=kpartx: CommandFilter, /sbin/kpartx, root
     - (ListOpt) Comma-separated list containing the filter class to
       use, followed by the Filter arguments (which vary depending
       on the Filter class selected).

Configure the rootwrap daemon
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Administrators can use rootwrap daemon support instead of running rootwrap with
:command:`sudo`. The rootwrap daemon reduces the overhead and performance loss
that results from running ``oslo.rootwrap`` with :command:`sudo`. Each call
that needs rootwrap privileges requires a new instance of rootwrap. The daemon
prevents overhead from the repeated calls. The daemon does not support long
running processes, however.

To enable the rootwrap daemon, set ``use_rootwrap_daemon`` to ``True`` in the
Compute service configuration file.
