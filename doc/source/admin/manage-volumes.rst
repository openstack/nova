==============
Manage volumes
==============

Depending on the setup of your cloud provider, they may give you an endpoint to
use to manage volumes, or there may be an extension under the covers. In either
case, you can use the ``openstack`` CLI to manage volumes.

.. list-table:: **openstack volume commands**
   :header-rows: 1

   * - Command
     - Description
   * - server add volume
     - Attach a volume to a server.
   * - volume create
     - Add a new volume.
   * - volume delete
     - Remove or delete a volume.
   * - server remove volume
     - Detach or remove a volume from a server.
   * - volume list
     - List all the volumes.
   * - volume show
     - Show details about a volume.
   * - snapshot create
     - Add a new snapshot.
   * - snapshot delete
     - Remove a snapshot.
   * - snapshot list
     - List all the snapshots.
   * - snapshot show
     - Show details about a snapshot.
   * - volume type create
     - Create a new volume type.
   * - volume type delete
     - Delete a specific flavor
   * - volume type list
     - Print a list of available 'volume types'.

|

For example, to list IDs and names of volumes, run:

.. code-block:: console

   $ openstack volume list
   +--------+--------------+-----------+------+-------------+
   | ID     | Display Name | Status    | Size | Attached to |
   +--------+--------------+-----------+------+-------------+
   | 86e6cb | testnfs      | available |    1 |             |
   | e389f7 | demo         | available |    1 |             |
   +--------+--------------+-----------+------+-------------+
