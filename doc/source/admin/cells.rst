==================
CellsV2 Management
==================

This section describes the various recommended practices/tips for runnning and
maintaining CellsV2 for admins and operators. For more details regarding the
basic concept of CellsV2 and its layout please see the main :doc:`/user/cellsv2-layout`
page.

.. _handling-cell-failures:

Handling cell failures
----------------------

For an explanation on how ``nova-api`` handles cell failures please see the
`Handling Down Cells <https://docs.openstack.org/api-guide/compute/down_cells.html>`__
section of the Compute API guide. Below, you can find some recommended practices and
considerations for effectively tolerating cell failure situations.

Configuration considerations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Since a cell being reachable or not is determined through timeouts, it is suggested
to provide suitable values for the following settings based on your requirements.

#. :oslo.config:option:`database.max_retries` is 10 by default meaning every time
   a cell becomes unreachable, it would retry 10 times before nova can declare the
   cell as a "down" cell.
#. :oslo.config:option:`database.retry_interval` is 10 seconds and
   :oslo.config:option:`oslo_messaging_rabbit.rabbit_retry_interval` is 1 second by
   default meaning every time a cell becomes unreachable it would retry every 10
   seconds or 1 second depending on if it's a database or a message queue problem.
#. Nova also has a timeout value called ``CELL_TIMEOUT`` which is hardcoded to 60
   seconds and that is the total time the nova-api would wait before returning
   partial results for the "down" cells.

The values of the above settings will affect the time required for nova to decide
if a cell is unreachable and then take the necessary actions like returning
partial results.

The operator can also control the results of certain actions like listing
servers and services depending on the value of the
:oslo.config:option:`api.list_records_by_skipping_down_cells` config option.
If this is true, the results from the unreachable cells will be skipped
and if it is false, the request will just fail with an API error in situations where
partial constructs cannot be computed.

Disabling down cells
~~~~~~~~~~~~~~~~~~~~

While the temporary outage in the infrastructure is being fixed, the affected
cells can be disabled so that they are removed from being scheduling candidates.
To enable or disable a cell, use :command:`nova-manage cell_v2 update_cell
--cell_uuid <cell_uuid> --disable`. See the :ref:`man-page-cells-v2` man page
for details on command usage.

Known issues
~~~~~~~~~~~~

1. **Services and Performance:** In case a cell is down during the startup of nova
   services, there is the chance that the services hang because of not being able
   to connect to all the cell databases that might be required for certain calculations
   and initializations. An example scenario of this situation is if
   :oslo.config:option:`upgrade_levels.compute` is set to ``auto`` then the
   ``nova-api`` service hangs on startup if there is at least one unreachable
   cell. This is because it needs to connect to all the cells to gather
   information on each of the compute service's version to determine the compute
   version cap to use. The current workaround is to pin the
   :oslo.config:option:`upgrade_levels.compute` to a particular version like
   "rocky" and get the service up under such situations. See `bug 1815697
   <https://bugs.launchpad.net/nova/+bug/1815697>`__ for more details. Also note
   that in general during situations where cells are not reachable certain
   "slowness" may be experienced in operations requiring hitting all the cells
   because of the aforementioned configurable timeout/retry values.

.. _cells-counting-quotas:

2. **Counting Quotas:** Another known issue is in the current approach of counting
   quotas where we query each cell database to get the used resources and aggregate
   them which makes it sensitive to temporary cell outages. While the cell is
   unavailable, we cannot count resource usage residing in that cell database and
   things would behave as though more quota is available than should be. That is,
   if a tenant has used all of their quota and part of it is in cell A and cell A
   goes offline temporarily, that tenant will suddenly be able to allocate more
   resources than their limit (assuming cell A returns, the tenant will have more
   resources allocated than their allowed quota).

   .. note:: Starting in the Train (20.0.0) release, it is possible to
             configure counting of quota usage from the placement service and
             API database to make quota usage calculations resilient to down or
             poor-performing cells in a multi-cell environment. See the
             :doc:`quotas documentation</user/quotas>` for more details.
