.. -*- rst -*-

==========================================================
 Servers - run an administrative action (servers, action)
==========================================================

Enables administrators to perform an action on a server. Specify the
action in the request body.

You can change the administrative password for, create a back up of, and
inject network information into a server.

You can migrate, live-migrate, reset networking on, and reset the state
of a server.

Create Server Back Up (createBackup Action)
===========================================

.. rest_method:: POST /servers/{server_id}/action

Creates a back up of a server.

Specify the ``createBackup`` action in the request body.

Policy defaults enable only users with the administrative role or the
owner of the server to perform this operation. Cloud providers can
change these permissions through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403),
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - createBackup: createBackup
  - name: backup_name
  - backup_type: backup_type
  - rotation: backup_rotation
  - metadata: metadata_image

**Example Create Server Back Up (Createbackup Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-create-backup/create-backup-req.json
   :language: javascript

Response
--------

On success a header 'Location' : <image location URL> and no body
will be returned.

Inject Network Information (injectNetworkInfo Action)
=====================================================

.. rest_method:: POST /servers/{server_id}/action

Injects network information into a server.

Specify the ``injectNetworkInfo`` action in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

.. warning:: There is very limited support on this API, For more information,
             see `nova virt support matrix
             <http://docs.openstack.org/developer/nova/support-matrix.html>`__

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - injectNetworkInfo: injectNetworkInfo

**Example Inject Network Information (injectNetworkInfo Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-inject-network-info.json
   :language: javascript

Response
--------

On success no body is returned.

Migrate Server (migrate Action)
===============================

.. rest_method:: POST /servers/{server_id}/action

Migrates a server to a host. The scheduler chooses the host.

Specify the ``migrate`` action in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403)
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - migrate: migrate

**Example Migrate Server (migrate Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/migrate-server.json
   :language: javascript

Response
--------

On success no body is returned.

Live-Migrate Server (os-migrateLive Action)
===========================================

.. rest_method:: POST /servers/{server_id}/action

Live-migrates a server to a new host without rebooting.

Specify the ``os-migrateLive`` action in the request body.

Use the ``host`` parameter to specify the destination host. If you
omit this parameter, the scheduler chooses a host. If a scheduled host
is not suitable to do migration, the scheduler tries up to
``migrate_max_retries`` rescheduling attempts.

If both source and destination hosts provide local disks, you can set
the ``block_migration`` parameter to ``true``. If either host uses
shared storage, the migration fails if you set this ``block_migration``
to ``true``.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: badRequest(400), unauthorized(401), forbidden(403)
itemNotFound(404), conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - host: host_migration
  - block_migration: block_migration
  - disk_over_commit: disk_over_commit
  - force: force_live_migrate

**Example Live-Migrate Server (os-migrateLive Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-migrate-server/live-migrate-server.json
   :language: javascript

Response
--------

On success no body is returned.

Reset Networking On A Server (resetNetwork Action)
==================================================

.. rest_method:: POST /servers/{server_id}/action

Resets networking on a server.

.. note::

    Only the XenServer driver implements this feature and only if the guest
    has the XenAPI agent in the targeted server.

Specify the ``resetNetwork`` action in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404),
conflict(409)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - resetNetwork: resetNetwork

**Example Reset Networking On A Server (resetNetwork Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-network.json
   :language: javascript

Response
--------

On success no body is returned.

Reset Server State (os-resetState Action)
=========================================

.. rest_method:: POST /servers/{server_id}/action

Resets the state of a server.

Specify the ``os-resetState`` action and the ``state`` in the request body.

Policy defaults enable only users with the administrative role to
perform this operation. Cloud providers can change these permissions
through the ``policy.json`` file.

Normal response codes: 202

Error response codes: unauthorized(401), forbidden(403), itemNotFound(404)

Request
-------

.. rest_parameters:: parameters.yaml


  - server_id: server_id
  - os-resetState: os-resetState
  - os-resetState.state: os-resetState_state

**Example Reset Server State (os-resetState Action): JSON request**

.. literalinclude:: ../../doc/api_samples/os-admin-actions/admin-actions-reset-server-state.json
   :language: javascript

Response
--------

On success no body is returned.
