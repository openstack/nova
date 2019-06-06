==================
Testing Down Cells
==================

This document describes how to recreate a down-cell scenario in a single-node
devstack environment. This can be useful for testing the reliability of the
controller services when a cell in the deployment is down.


Setup
=====

DevStack config
---------------

This guide is based on a devstack install from the Train release using
an Ubuntu Bionic 18.04 VM with 8 VCPU, 8 GB RAM and 200 GB of disk following
the `All-In-One Single Machine`_ guide.

The following minimal local.conf was used:

.. code-block:: ini

  [[local|localrc]]
  # Define passwords
  OS_PASSWORD=openstack1
  SERVICE_TOKEN=$OS_PASSWORD
  ADMIN_PASSWORD=$OS_PASSWORD
  MYSQL_PASSWORD=$OS_PASSWORD
  RABBIT_PASSWORD=$OS_PASSWORD
  SERVICE_PASSWORD=$OS_PASSWORD
  # Logging config
  LOGFILE=$DEST/logs/stack.sh.log
  LOGDAYS=2
  # Disable non-essential services
  disable_service horizon tempest

.. _All-In-One Single Machine: https://docs.openstack.org/devstack/latest/guides/single-machine.html

Populate cell1
--------------

Create a test server first so there is something in cell1:

.. code-block:: console

  $ source openrc admin admin
  $ IMAGE=$(openstack image list -f value -c ID)
  $ openstack server create --wait --flavor m1.tiny --image $IMAGE cell1-server


Take down cell1
===============

Break the connection to the cell1 database by changing the
``database_connection`` URL, in this case with an invalid host IP:

.. code-block:: console

  mysql> select database_connection from cell_mappings where name='cell1';
  +-------------------------------------------------------------------+
  | database_connection                                               |
  +-------------------------------------------------------------------+
  | mysql+pymysql://root:openstack1@127.0.0.1/nova_cell1?charset=utf8 |
  +-------------------------------------------------------------------+
  1 row in set (0.00 sec)

  mysql> update cell_mappings set database_connection='mysql+pymysql://root:openstack1@192.0.0.1/nova_cell1?charset=utf8' where name='cell1';
  Query OK, 1 row affected (0.01 sec)
  Rows matched: 1  Changed: 1  Warnings: 0


Update controller services
==========================

Prepare the controller services for the down cell. See
:ref:`Handling cell failures <handling-cell-failures>` for details.

Modify nova.conf
----------------

Configure the API to avoid long timeouts and slow start times due to
`bug 1815697`_ by modifying ``/etc/nova/nova.conf``:

.. code-block:: ini

  [database]
  ...
  max_retries = 1
  retry_interval = 1

  [upgrade_levels]
  ...
  compute = stein  # N-1 from train release, just something other than "auto"

.. _bug 1815697: https://bugs.launchpad.net/nova/+bug/1815697

Restart services
----------------

.. note:: It is useful to tail the n-api service logs in another screen to
          watch for errors / warnings in the logs due to down cells:

          .. code-block:: console

            $ sudo journalctl -f -a -u devstack@n-api.service

Restart controller services to flush the cell cache:

.. code-block:: console

  $ sudo systemctl restart devstack@n-api.service devstack@n-super-cond.service devstack@n-sch.service


Test cases
==========

1. Try to create a server which should fail and go to cell0.

   .. code-block:: console

     $ openstack server create --wait --flavor m1.tiny --image $IMAGE cell0-server

   You can expect to see errors like this in the n-api logs:

   .. code-block:: console

     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context [None req-fdaff415-48b9-44a7-b4c3-015214e80b90 None None] Error gathering result from cell 4f495a21-294a-4051-9a3d-8b34a250bbb4: DBConnectionError: (pymysql.err.OperationalError) (2003, "Can't connect to MySQL server on u'192.0.0.1' ([Errno 101] ENETUNREACH)") (Background on this error at: http://sqlalche.me/e/e3q8)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context Traceback (most recent call last):
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/opt/stack/nova/nova/context.py", line 441, in gather_result
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     result = fn(cctxt, *args, **kwargs)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/opt/stack/nova/nova/db/sqlalchemy/api.py", line 211, in wrapper
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     with reader_mode.using(context):
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/lib/python2.7/contextlib.py", line 17, in __enter__
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     return self.gen.next()
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/enginefacade.py", line 1061, in _transaction_scope
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     context=context) as resource:
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/lib/python2.7/contextlib.py", line 17, in __enter__
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     return self.gen.next()
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/enginefacade.py", line 659, in _session
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     bind=self.connection, mode=self.mode)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/enginefacade.py", line 418, in _create_session
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     self._start()
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/enginefacade.py", line 510, in _start
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     engine_args, maker_args)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/enginefacade.py", line 534, in _setup_for_connection
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     sql_connection=sql_connection, **engine_kwargs)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/debtcollector/renames.py", line 43, in decorator
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     return wrapped(*args, **kwargs)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/engines.py", line 201, in create_engine
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     test_conn = _test_connection(engine, max_retries, retry_interval)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "/usr/local/lib/python2.7/dist-packages/oslo_db/sqlalchemy/engines.py", line 387, in _test_connection
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context     six.reraise(type(de_ref), de_ref)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context   File "<string>", line 3, in reraise
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context DBConnectionError: (pymysql.err.OperationalError) (2003, "Can't connect to MySQL server on u'192.0.0.1' ([Errno 101] ENETUNREACH)") (Background on this error at: http://sqlalche.me/e/e3q8)
     Apr 04 20:48:22 train devstack@n-api.service[10884]: ERROR nova.context
     Apr 04 20:48:22 train devstack@n-api.service[10884]: WARNING nova.objects.service [None req-1cf4bf5c-2f74-4be0-a18d-51ff81df57dd admin admin] Failed to get minimum service version for cell 4f495a21-294a-4051-9a3d-8b34a250bbb4

2. List servers with the 2.69 microversion for down cells.

   .. note:: Requires python-openstackclient >= 3.18.0 for v2.69 support.

   The server in cell1 (which is down) will show up with status UNKNOWN:

   .. code-block:: console

     $ openstack --os-compute-api-version 2.69 server list
     +--------------------------------------+--------------+---------+----------+--------------------------+--------+
     | ID                                   | Name         | Status  | Networks | Image                    | Flavor |
     +--------------------------------------+--------------+---------+----------+--------------------------+--------+
     | 8e90f1f0-e8dd-4783-8bb3-ec8d594e60f1 |              | UNKNOWN |          |                          |        |
     | afd45d84-2bd7-4e49-9dff-93359f742bc1 | cell0-server | ERROR   |          | cirros-0.4.0-x86_64-disk |        |
     +--------------------------------------+--------------+---------+----------+--------------------------+--------+

3. Using v2.1 the UNKNOWN server is filtered out by default due to
   :oslo.config:option:`api.list_records_by_skipping_down_cells`:

   .. code-block:: console

     $ openstack --os-compute-api-version 2.1 server list
     +--------------------------------------+--------------+--------+----------+--------------------------+---------+
     | ID                                   | Name         | Status | Networks | Image                    | Flavor  |
     +--------------------------------------+--------------+--------+----------+--------------------------+---------+
     | afd45d84-2bd7-4e49-9dff-93359f742bc1 | cell0-server | ERROR  |          | cirros-0.4.0-x86_64-disk | m1.tiny |
     +--------------------------------------+--------------+--------+----------+--------------------------+---------+

4. Configure nova-api with ``list_records_by_skipping_down_cells=False``

   .. code-block:: ini

     [api]
     list_records_by_skipping_down_cells = False

5. Restart nova-api and then listing servers should fail:

   .. code-block:: console

      $ sudo systemctl restart devstack@n-api.service
      $ openstack --os-compute-api-version 2.1 server list
      Unexpected API Error. Please report this at http://bugs.launchpad.net/nova/ and attach the Nova API log if possible.
      <class 'nova.exception.NovaException'> (HTTP 500) (Request-ID: req-e2264d67-5b6c-4f17-ae3d-16c7562f1b69)

6. Try listing compute services with a down cell.

   The services from the down cell are skipped:

   .. code-block:: console

     $ openstack --os-compute-api-version 2.1 compute service list
     +----+------------------+-------+----------+---------+-------+----------------------------+
     | ID | Binary           | Host  | Zone     | Status  | State | Updated At                 |
     +----+------------------+-------+----------+---------+-------+----------------------------+
     |  2 | nova-scheduler   | train | internal | enabled | up    | 2019-04-04T21:12:47.000000 |
     |  6 | nova-consoleauth | train | internal | enabled | up    | 2019-04-04T21:12:38.000000 |
     |  7 | nova-conductor   | train | internal | enabled | up    | 2019-04-04T21:12:47.000000 |
     +----+------------------+-------+----------+---------+-------+----------------------------+

   With 2.69 the nova-compute service from cell1 is shown with status UNKNOWN:

   .. code-block:: console

     $ openstack --os-compute-api-version 2.69 compute service list
     +--------------------------------------+------------------+-------+----------+---------+-------+----------------------------+
     | ID                                   | Binary           | Host  | Zone     | Status  | State | Updated At                 |
     +--------------------------------------+------------------+-------+----------+---------+-------+----------------------------+
     | f68a96d9-d994-4122-a8f9-1b0f68ed69c2 | nova-scheduler   | train | internal | enabled | up    | 2019-04-04T21:13:47.000000 |
     | 70cd668a-6d60-4a9a-ad83-f863920d4c44 | nova-consoleauth | train | internal | enabled | up    | 2019-04-04T21:13:38.000000 |
     | ca88f023-1de4-49e0-90b0-581e16bebaed | nova-conductor   | train | internal | enabled | up    | 2019-04-04T21:13:47.000000 |
     |                                      | nova-compute     | train |          | UNKNOWN |       |                            |
     +--------------------------------------+------------------+-------+----------+---------+-------+----------------------------+


Future
======

This guide could be expanded for having multiple non-cell0 cells where one
cell is down while the other is available and go through scenarios where the
down cell is marked as disabled to take it out of scheduling consideration.
