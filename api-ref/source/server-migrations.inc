.. -*- rst -*-
.. needs:parameter_verification
.. needs:example_verification
.. needs:body_verification

=========================================
 Server migrations (servers, migrations)
=========================================

List, show, perform actions on and delete server migrations.

List Migrations
===============

.. rest_method:: GET /servers/{server_id}/migrations

Show Migration Details
======================

.. rest_method:: GET /servers/{server_id}/migrations/{migration_id}

Force Migration Complete Action (force_complete Action)
=======================================================

.. rest_method:: POST /servers/{server_id}/migrations/{migration_id}/action

Delete (Abort) Migration
========================

.. rest_method:: DELETE /servers/{server_id}/migrations/{migration_id}
