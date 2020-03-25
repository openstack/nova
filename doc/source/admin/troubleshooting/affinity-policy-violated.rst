Affinity policy violated with parallel requests
===============================================

Problem
-------

Parallel server create requests for affinity or anti-affinity land on the same
host and servers go to the ``ACTIVE`` state even though the affinity or
anti-affinity policy was violated.

Solution
--------

There are two ways to avoid anti-/affinity policy violations among multiple
server create requests.

Create multiple servers as a single request
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use the `multi-create API`_ with the ``min_count`` parameter set or the
`multi-create CLI`_ with the ``--min`` option set to the desired number of
servers.

This works because when the batch of requests is visible to ``nova-scheduler``
at the same time as a group, it will be able to choose compute hosts that
satisfy the anti-/affinity constraint and will send them to the same hosts or
different hosts accordingly.

.. _multi-create API: https://docs.openstack.org/api-ref/compute/#create-multiple-servers
.. _multi-create CLI: https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/server.html#server-create

Adjust Nova configuration settings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When requests are made separately and the scheduler cannot consider the batch
of requests at the same time as a group, anti-/affinity races are handled by
what is called the "late affinity check" in ``nova-compute``. Once a server
lands on a compute host, if the request involves a server group,
``nova-compute`` contacts the API database (via ``nova-conductor``) to retrieve
the server group and then it checks whether the affinity policy has been
violated. If the policy has been violated, ``nova-compute`` initiates a
reschedule of the server create request.  Note that this means the deployment
must have :oslo.config:option:`scheduler.max_attempts` set greater than ``1``
(default is ``3``) to handle races.

An ideal configuration for multiple cells will minimize `upcalls`_ from the
cells to the API database. This is how devstack, for example, is configured in
the CI gate. The cell conductors do not set
:oslo.config:option:`api_database.connection` and ``nova-compute`` sets
:oslo.config:option:`workarounds.disable_group_policy_check_upcall` to
``True``.

However, if a deployment needs to handle racing affinity requests, it needs to
configure cell conductors to have access to the API database, for example:

.. code-block:: ini

  [api_database]
  connection = mysql+pymysql://root:a@127.0.0.1/nova_api?charset=utf8

The deployment also needs to configure ``nova-compute`` services not to disable
the group policy check upcall by either not setting (use the default)
:oslo.config:option:`workarounds.disable_group_policy_check_upcall` or setting
it to ``False``, for example:

.. code-block:: ini

  [workarounds]
  disable_group_policy_check_upcall = False

With these settings, anti-/affinity policy should not be violated even when
parallel server create requests are racing.

Future work is needed to add anti-/affinity support to the placement service in
order to eliminate the need for the late affinity check in ``nova-compute``.

.. _upcalls: https://docs.openstack.org/nova/latest/user/cellsv2-layout.html#operations-requiring-upcalls

