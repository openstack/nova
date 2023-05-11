===================
Database migrations
===================

.. note::

   This document details how to generate database migrations as part of a new
   feature or bugfix. For info on how to apply existing database migrations,
   refer to the documentation for the :program:`nova-manage db sync` and
   :program:`nova-manage api_db sync` commands in :doc:`/cli/nova-manage`.
   For info on the general upgrade process for a nova deployment, refer to
   :doc:`/admin/upgrades`.

A typical nova deployments consists of an "API" database and one or more
cell-specific "main" databases. Occasionally these databases will require
schema or data migrations.


Schema migrations
-----------------

.. versionchanged:: 24.0.0 (Xena)

   The database migration engine was changed from ``sqlalchemy-migrate`` to
   ``alembic``.

.. versionchanged:: 28.0.0 (Bobcat)

   The legacy ``sqlalchemy-migrate``-based database migrations were removed.

The `alembic`__ database migration tool is used to manage schema migrations in
nova. The migration files and related metadata can be found in
``nova/db/api/migrations`` (for the API database) and
``nova/db/main/migrations`` (for the main database(s)). As discussed in
:doc:`/admin/upgrades`, these can be run by end users using the
:program:`nova-manage api_db sync` and :program:`nova-manage db sync` commands,
respectively.

.. __: https://alembic.sqlalchemy.org/en/latest/

.. note::

   There were also legacy migrations provided in the ``legacy_migrations``
   subdirectory for both the API and main databases. These were provided to
   facilitate upgrades from pre-Xena (24.0.0) deployments. They were removed
   in the 28.0.0 (Bobcat) release.

The best reference for alembic is the `alembic documentation`__, but a small
example is provided here. You can create the migration either manually or
automatically. Manual generation might be necessary for some corner cases such
as renamed tables but auto-generation will typically handle your issues.
Examples of both are provided below. In both examples, we're going to
demonstrate how you could add a new model, ``Foo``, to the main database.

.. __: https://alembic.sqlalchemy.org/en/latest/

.. code-block:: diff

   diff --git nova/db/main/models.py nova/db/main/models.py
   index 7eab643e14..8f70bcdaca 100644
   --- nova/db/main/models.py
   +++ nova/db/main/models.py
   @@ -73,6 +73,16 @@ def MediumText():
            sqlalchemy.dialects.mysql.MEDIUMTEXT(), 'mysql')


   +class Foo(BASE, models.SoftDeleteMixin):
   +    """A test-only model."""
   +
   +    __tablename__ = 'foo'
   +
   +    id = sa.Column(sa.Integer, primary_key=True)
   +    uuid = sa.Column(sa.String(36), nullable=True)
   +    bar = sa.Column(sa.String(255))
   +
   +
    class Service(BASE, models.SoftDeleteMixin):
        """Represents a running service on a host."""

(you might not be able to apply the diff above cleanly - this is just a demo).

.. rubric:: Auto-generating migration scripts

In order for alembic to compare the migrations with the underlying models, it
require a database that it can inspect and compare the models against. As such,
we first need to create a working database. We'll bypass ``nova-manage`` for
this and go straight to the :program:`alembic` CLI. The ``alembic.ini`` file
provided in the ``migrations`` directories for both databases is helpfully
configured to use an SQLite database by default (``nova.db`` for the main
database and ``nova_api.db`` for the API database). Create this database and
apply the current schema, as dictated by the current migration scripts:

.. code-block:: bash

   $ tox -e venv -- alembic -c nova/db/main/alembic.ini \
       upgrade head

Once done, you should notice the new ``nova.db`` file in the root of the repo.
Now, let's generate the new revision:

.. code-block:: bash

   $ tox -e venv -- alembic -c nova/db/main/alembic.ini \
       revision -m "Add foo model" --autogenerate

This will create a new file in ``nova/db/main/migrations`` with
``add_foo_model`` in the name including (hopefully!) the necessary changes to
add the new ``Foo`` model. You **must** inspect this file once created, since
there's a chance you'll be missing imports or something else which will need to
be manually corrected. Once you've inspected this file and made any required
changes, you can apply the migration and make sure it works:

.. code-block:: bash

   $ tox -e venv -- alembic -c nova/db/main/alembic.ini \
       upgrade head

.. rubric:: Manually generating migration scripts

For trickier migrations or things that alembic doesn't understand, you may need
to manually create a migration script. This is very similar to the
auto-generation step, with the exception being that you don't need to have a
database in place beforehand. As such, you can simply run:

.. code-block:: bash

   $ tox -e venv -- alembic -c nova/db/main/alembic.ini \
       revision -m "Add foo model"

As before, this will create a new file in ``nova/db/main/migrations`` with
``add_foo_model`` in the name. You can simply modify this to make whatever
changes are necessary. Once done, you can apply the migration and make sure it
works:

.. code-block:: bash

   $ tox -e venv -- alembic -c nova/db/main/alembic.ini \
       upgrade head


Data migrations
---------------

As discussed in :doc:`/admin/upgrades`, online data migrations occur in two
places:

- Inline migrations that occur as part of normal run-time activity as data is
  read in the old format and written in the new format.

- Background online migrations that are performed using ``nova-manage`` to
  complete transformations that will not occur incidentally due to normal
  runtime activity.

.. rubric:: Inline data migrations

Inline data migrations are arguably the easier of the two to implement. Almost
all of nova's database models correspond to an oslo.versionedobject (o.vo) or
part of one. These o.vos load their data from the underlying database by
implementing the ``obj_load_attr`` method. By modifying this method, it's
possible to detect missing changes to the data - for example, a missing field -
modify the data, save it back to the database, and finally return an object
with the newly updated data. Change I6cd206542fdd28f3ef551dcc727f4cb35a53f6a3
provides a fully worked example of this approach.

The main advantage of these is that they are completely transparent to the
operator who does not have to take any additional steps to upgrade their
deployment: the database updates should happen at runtime as data is pulled
from the database. The main disadvantage of this approach is that some
records may not be frequently pulled from the database, meaning they never have
a chance to get updated. This can prevent the eventual removal of the inline
migration in a future release. To avoid this issue, you should inspect the
object to see if it's something that will be loaded as part of a standard
runtime operation - for example, on startup or as part of a background task -
and if necessary add a blocking online migration in a later release to catch
and migrate the laggards.

.. rubric:: Online data migrations

Unlike inline data migrations, online data migrations require operator
involvement. They are run using the ``nova-manage db online_data_migrations``
command which, as noted in :doc:`/cli/nova-manage`, this should be run straight
after upgrading to a new release once the database schema migrations have been
applied and the code updated. Online migrations can be blocking, in that it
will be necessary to apply given migrations while running N code before
upgrading to N+1. Change I44919422c48570f2647f2325ff895255fc2adf27 provides a
fully worked example of this approach.

The advantages and disadvantages of this approach are the inverse of those of
the inline data migrations approach. While they can be used to ensure an data
migration is actually applied, they require operator involvement and can
prevent upgrades until fully applied.
