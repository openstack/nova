=======
Logging
=======

Logging module
~~~~~~~~~~~~~~

Logging behavior can be changed by creating a configuration file. To specify
the configuration file, add this line to the ``/etc/nova/nova.conf`` file:

.. code-block:: ini

   log-config=/etc/nova/logging.conf

To change the logging level, add ``DEBUG``, ``INFO``, ``WARNING``, or ``ERROR``
as a parameter.

The logging configuration file is an INI-style configuration file, which must
contain a section called ``logger_nova``. This controls the behavior of the
logging facility in the ``nova-*`` services. For example:

.. code-block:: ini

   [logger_nova]
   level = INFO
   handlers = stderr
   qualname = nova

This example sets the debugging level to ``INFO`` (which is less verbose than
the default ``DEBUG`` setting).

For more about the logging configuration syntax, including the ``handlers`` and
``qualname`` variables, see the `Python documentation
<https://docs.python.org/release/2.7/library/logging.html#configuration-file-format>`__
on logging configuration files.

For an example of the ``logging.conf`` file with various defined handlers, see
the `Example Configuration File for nova
<https://docs.openstack.org/oslo.log/latest/admin/example_nova.html>`__.

Syslog
~~~~~~

OpenStack Compute services can send logging information to syslog. This is
useful if you want to use rsyslog to forward logs to a remote machine.
Separately configure the Compute service (nova), the Identity service
(keystone), the Image service (glance), and, if you are using it, the Block
Storage service (cinder) to send log messages to syslog.  Open these
configuration files:

-  ``/etc/nova/nova.conf``

-  ``/etc/keystone/keystone.conf``

-  ``/etc/glance/glance-api.conf``

-  ``/etc/glance/glance-registry.conf``

-  ``/etc/cinder/cinder.conf``

In each configuration file, add these lines:

.. code-block:: ini

   debug = False
   use_syslog = True
   syslog_log_facility = LOG_LOCAL0

In addition to enabling syslog, these settings also turn off debugging output
from the log.

.. note::

   Although this example uses the same local facility for each service
   (``LOG_LOCAL0``, which corresponds to syslog facility ``LOCAL0``), we
   recommend that you configure a separate local facility for each service, as
   this provides better isolation and more flexibility. For example, you can
   capture logging information at different severity levels for different
   services. syslog allows you to define up to eight local facilities,
   ``LOCAL0, LOCAL1, ..., LOCAL7``. For more information, see the syslog
   documentation.

Rsyslog
~~~~~~~

rsyslog is useful for setting up a centralized log server across multiple
machines. This section briefly describe the configuration to set up an rsyslog
server. A full treatment of rsyslog is beyond the scope of this book. This
section assumes rsyslog has already been installed on your hosts (it is
installed by default on most Linux distributions).

This example provides a minimal configuration for ``/etc/rsyslog.conf`` on the
log server host, which receives the log files

.. code-block:: console

   # provides TCP syslog reception
   $ModLoad imtcp
   $InputTCPServerRun 1024

Add a filter rule to ``/etc/rsyslog.conf`` which looks for a host name.  This
example uses COMPUTE_01 as the compute host name:

.. code-block:: none

   :hostname, isequal, "COMPUTE_01" /mnt/rsyslog/logs/compute-01.log

On each compute host, create a file named ``/etc/rsyslog.d/60-nova.conf``, with
the following content:

.. code-block:: none

   # prevent debug from dnsmasq with the daemon.none parameter
   *.*;auth,authpriv.none,daemon.none,local0.none -/var/log/syslog
   # Specify a log level of ERROR
   local0.error    @@172.20.1.43:1024

Once you have created the file, restart the ``rsyslog`` service. Error-level
log messages on the compute hosts should now be sent to the log server.

Serial console
~~~~~~~~~~~~~~

The serial console provides a way to examine kernel output and other system
messages during troubleshooting if the instance lacks network connectivity.

Read-only access from server serial console is possible using the
``os-GetSerialOutput`` server action. Most cloud images enable this feature by
default. For more information, see :ref:`compute-common-errors-and-fixes`.

OpenStack Juno and later supports read-write access using the serial console
using the ``os-GetSerialConsole`` server action. This feature also requires a
websocket client to access the serial console.

.. rubric:: Configuring read-write serial console access

#. On a compute node, edit the ``/etc/nova/nova.conf`` file:

   In the ``[serial_console]`` section, enable the serial console:

   .. code-block:: ini

      [serial_console]
      # ...
      enabled = true

#. In the ``[serial_console]`` section, configure the serial console proxy
   similar to graphical console proxies:

   .. code-block:: ini

      [serial_console]
      # ...
      base_url = ws://controller:6083/
      listen = 0.0.0.0
      proxyclient_address = MANAGEMENT_INTERFACE_IP_ADDRESS

   The ``base_url`` option specifies the base URL that clients receive from the
   API upon requesting a serial console. Typically, this refers to the host
   name of the controller node.

   The ``listen`` option specifies the network interface nova-compute should
   listen on for virtual console connections. Typically, 0.0.0.0 will enable
   listening on all interfaces.

   The ``proxyclient_address`` option specifies which network interface the
   proxy should connect to. Typically, this refers to the IP address of the
   management interface.

   When you enable read-write serial console access, Compute will add serial
   console information to the Libvirt XML file for the instance. For example:

   .. code-block:: xml

      <console type='tcp'>
        <source mode='bind' host='127.0.0.1' service='10000'/>
        <protocol type='raw'/>
        <target type='serial' port='0'/>
        <alias name='serial0'/>
      </console>

.. rubric:: Accessing the serial console on an instance

#. Use the :command:`nova get-serial-proxy` command to retrieve the websocket
   URL for the serial console on the instance:

   .. code-block:: console

      $ nova get-serial-proxy INSTANCE_NAME

   .. list-table::
      :header-rows: 0
      :widths: 9 65

      * - Type
        - Url
      * - serial
        - ws://127.0.0.1:6083/?token=18510769-71ad-4e5a-8348-4218b5613b3d

   Alternatively, use the API directly:

   .. code-block:: console

      $ curl -i 'http://<controller>:8774/v2.1/<tenant_uuid>/servers/<instance_uuid>/action' \
        -X POST \
        -H "Accept: application/json" \
        -H "Content-Type: application/json" \
        -H "X-Auth-Project-Id: <project_id>" \
        -H "X-Auth-Token: <auth_token>" \
        -d '{"os-getSerialConsole": {"type": "serial"}}'

#. Use Python websocket with the URL to generate ``.send``, ``.recv``, and
   ``.fileno`` methods for serial console access. For example:

   .. code-block:: python

      import websocket
      ws = websocket.create_connection(
          'ws://127.0.0.1:6083/?token=18510769-71ad-4e5a-8348-4218b5613b3d',
          subprotocols=['binary', 'base64'])

Alternatively, use a `Python websocket client
<https://github.com/larsks/novaconsole/>`__.

.. note::

   When you enable the serial console, typical instance logging using the
   :command:`nova console-log` command is disabled. Kernel output and other
   system messages will not be visible unless you are actively viewing the
   serial console.
