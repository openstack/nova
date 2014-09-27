# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

"""Session Handling for SQLAlchemy backend.

Recommended ways to use sessions within this framework:

* Don't use them explicitly; this is like running with ``AUTOCOMMIT=1``.
  `model_query()` will implicitly use a session when called without one
  supplied. This is the ideal situation because it will allow queries
  to be automatically retried if the database connection is interrupted.

  .. note:: Automatic retry will be enabled in a future patch.

  It is generally fine to issue several queries in a row like this. Even though
  they may be run in separate transactions and/or separate sessions, each one
  will see the data from the prior calls. If needed, undo- or rollback-like
  functionality should be handled at a logical level. For an example, look at
  the code around quotas and `reservation_rollback()`.

  Examples:

  .. code:: python

    def get_foo(context, foo):
        return (model_query(context, models.Foo).
                filter_by(foo=foo).
                first())

    def update_foo(context, id, newfoo):
        (model_query(context, models.Foo).
                filter_by(id=id).
                update({'foo': newfoo}))

    def create_foo(context, values):
        foo_ref = models.Foo()
        foo_ref.update(values)
        foo_ref.save()
        return foo_ref


* Within the scope of a single method, keep all the reads and writes within
  the context managed by a single session. In this way, the session's
  `__exit__` handler will take care of calling `flush()` and `commit()` for
  you. If using this approach, you should not explicitly call `flush()` or
  `commit()`. Any error within the context of the session will cause the
  session to emit a `ROLLBACK`. Database errors like `IntegrityError` will be
  raised in `session`'s `__exit__` handler, and any try/except within the
  context managed by `session` will not be triggered. And catching other
  non-database errors in the session will not trigger the ROLLBACK, so
  exception handlers should  always be outside the session, unless the
  developer wants to do a partial commit on purpose. If the connection is
  dropped before this is possible, the database will implicitly roll back the
  transaction.

  .. note:: Statements in the session scope will not be automatically retried.

  If you create models within the session, they need to be added, but you
  do not need to call `model.save()`:

  .. code:: python

    def create_many_foo(context, foos):
        session = sessionmaker()
        with session.begin():
            for foo in foos:
                foo_ref = models.Foo()
                foo_ref.update(foo)
                session.add(foo_ref)

    def update_bar(context, foo_id, newbar):
        session = sessionmaker()
        with session.begin():
            foo_ref = (model_query(context, models.Foo, session).
                        filter_by(id=foo_id).
                        first())
            (model_query(context, models.Bar, session).
                        filter_by(id=foo_ref['bar_id']).
                        update({'bar': newbar}))

  .. note:: `update_bar` is a trivially simple example of using
     ``with session.begin``. Whereas `create_many_foo` is a good example of
     when a transaction is needed, it is always best to use as few queries as
     possible.

  The two queries in `update_bar` can be better expressed using a single query
  which avoids the need for an explicit transaction. It can be expressed like
  so:

  .. code:: python

    def update_bar(context, foo_id, newbar):
        subq = (model_query(context, models.Foo.id).
                filter_by(id=foo_id).
                limit(1).
                subquery())
        (model_query(context, models.Bar).
                filter_by(id=subq.as_scalar()).
                update({'bar': newbar}))

  For reference, this emits approximately the following SQL statement:

  .. code:: sql

    UPDATE bar SET bar = ${newbar}
        WHERE id=(SELECT bar_id FROM foo WHERE id = ${foo_id} LIMIT 1);

  .. note:: `create_duplicate_foo` is a trivially simple example of catching an
     exception while using ``with session.begin``. Here create two duplicate
     instances with same primary key, must catch the exception out of context
     managed by a single session:

  .. code:: python

    def create_duplicate_foo(context):
        foo1 = models.Foo()
        foo2 = models.Foo()
        foo1.id = foo2.id = 1
        session = sessionmaker()
        try:
            with session.begin():
                session.add(foo1)
                session.add(foo2)
        except exception.DBDuplicateEntry as e:
            handle_error(e)

* Passing an active session between methods. Sessions should only be passed
  to private methods. The private method must use a subtransaction; otherwise
  SQLAlchemy will throw an error when you call `session.begin()` on an existing
  transaction. Public methods should not accept a session parameter and should
  not be involved in sessions within the caller's scope.

  Note that this incurs more overhead in SQLAlchemy than the above means
  due to nesting transactions, and it is not possible to implicitly retry
  failed database operations when using this approach.

  This also makes code somewhat more difficult to read and debug, because a
  single database transaction spans more than one method. Error handling
  becomes less clear in this situation. When this is needed for code clarity,
  it should be clearly documented.

  .. code:: python

    def myfunc(foo):
        session = sessionmaker()
        with session.begin():
            # do some database things
            bar = _private_func(foo, session)
        return bar

    def _private_func(foo, session=None):
        if not session:
            session = sessionmaker()
        with session.begin(subtransaction=True):
            # do some other database things
        return bar


There are some things which it is best to avoid:

* Don't keep a transaction open any longer than necessary.

  This means that your ``with session.begin()`` block should be as short
  as possible, while still containing all the related calls for that
  transaction.

* Avoid ``with_lockmode('UPDATE')`` when possible.

  In MySQL/InnoDB, when a ``SELECT ... FOR UPDATE`` query does not match
  any rows, it will take a gap-lock. This is a form of write-lock on the
  "gap" where no rows exist, and prevents any other writes to that space.
  This can effectively prevent any INSERT into a table by locking the gap
  at the end of the index. Similar problems will occur if the SELECT FOR UPDATE
  has an overly broad WHERE clause, or doesn't properly use an index.

  One idea proposed at ODS Fall '12 was to use a normal SELECT to test the
  number of rows matching a query, and if only one row is returned,
  then issue the SELECT FOR UPDATE.

  The better long-term solution is to use
  ``INSERT .. ON DUPLICATE KEY UPDATE``.
  However, this can not be done until the "deleted" columns are removed and
  proper UNIQUE constraints are added to the tables.


Enabling soft deletes:

* To use/enable soft-deletes, the `SoftDeleteMixin` must be added
  to your model class. For example:

  .. code:: python

      class NovaBase(models.SoftDeleteMixin, models.ModelBase):
          pass


Efficient use of soft deletes:

* There are two possible ways to mark a record as deleted:
  `model.soft_delete()` and `query.soft_delete()`.

  The `model.soft_delete()` method works with a single already-fetched entry.
  `query.soft_delete()` makes only one db request for all entries that
  correspond to the query.

* In almost all cases you should use `query.soft_delete()`. Some examples:

  .. code:: python

        def soft_delete_bar():
            count = model_query(BarModel).find(some_condition).soft_delete()
            if count == 0:
                raise Exception("0 entries were soft deleted")

        def complex_soft_delete_with_synchronization_bar(session=None):
            if session is None:
                session = sessionmaker()
            with session.begin(subtransactions=True):
                count = (model_query(BarModel).
                            find(some_condition).
                            soft_delete(synchronize_session=True))
                            # Here synchronize_session is required, because we
                            # don't know what is going on in outer session.
                if count == 0:
                    raise Exception("0 entries were soft deleted")

* There is only one situation where `model.soft_delete()` is appropriate: when
  you fetch a single record, work with it, and mark it as deleted in the same
  transaction.

  .. code:: python

        def soft_delete_bar_model():
            session = sessionmaker()
            with session.begin():
                bar_ref = model_query(BarModel).find(some_condition).first()
                # Work with bar_ref
                bar_ref.soft_delete(session=session)

  However, if you need to work with all entries that correspond to query and
  then soft delete them you should use the `query.soft_delete()` method:

  .. code:: python

        def soft_delete_multi_models():
            session = sessionmaker()
            with session.begin():
                query = (model_query(BarModel, session=session).
                            find(some_condition))
                model_refs = query.all()
                # Work with model_refs
                query.soft_delete(synchronize_session=False)
                # synchronize_session=False should be set if there is no outer
                # session and these entries are not used after this.

  When working with many rows, it is very important to use query.soft_delete,
  which issues a single query. Using `model.soft_delete()`, as in the following
  example, is very inefficient.

  .. code:: python

        for bar_ref in bar_refs:
            bar_ref.soft_delete(session=session)
        # This will produce count(bar_refs) db requests.

"""

import functools
import logging
import re
import time

import six
from sqlalchemy import exc as sqla_exc
from sqlalchemy.interfaces import PoolListener
import sqlalchemy.orm
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.sql.expression import literal_column

from nova.openstack.common.db import exception
from nova.openstack.common.gettextutils import _LE, _LW, _LI
from nova.openstack.common import timeutils


LOG = logging.getLogger(__name__)


class SqliteForeignKeysListener(PoolListener):
    """Ensures that the foreign key constraints are enforced in SQLite.

    The foreign key constraints are disabled by default in SQLite,
    so the foreign key constraints will be enabled here for every
    database connection
    """
    def connect(self, dbapi_con, con_record):
        dbapi_con.execute('pragma foreign_keys=ON')


# note(boris-42): In current versions of DB backends unique constraint
# violation messages follow the structure:
#
# sqlite:
# 1 column - (IntegrityError) column c1 is not unique
# N columns - (IntegrityError) column c1, c2, ..., N are not unique
#
# sqlite since 3.7.16:
# 1 column - (IntegrityError) UNIQUE constraint failed: tbl.k1
#
# N columns - (IntegrityError) UNIQUE constraint failed: tbl.k1, tbl.k2
#
# postgres:
# 1 column - (IntegrityError) duplicate key value violates unique
#               constraint "users_c1_key"
# N columns - (IntegrityError) duplicate key value violates unique
#               constraint "name_of_our_constraint"
#
# mysql:
# 1 column - (IntegrityError) (1062, "Duplicate entry 'value_of_c1' for key
#               'c1'")
# N columns - (IntegrityError) (1062, "Duplicate entry 'values joined
#               with -' for key 'name_of_our_constraint'")
#
# ibm_db_sa:
# N columns - (IntegrityError) SQL0803N  One or more values in the INSERT
#                statement, UPDATE statement, or foreign key update caused by a
#                DELETE statement are not valid because the primary key, unique
#                constraint or unique index identified by "2" constrains table
#                "NOVA.KEY_PAIRS" from having duplicate values for the index
#                key.
_DUP_KEY_RE_DB = {
    "sqlite": (re.compile(r"^.*columns?([^)]+)(is|are)\s+not\s+unique$"),
               re.compile(r"^.*UNIQUE\s+constraint\s+failed:\s+(.+)$")),
    "postgresql": (re.compile(r"^.*duplicate\s+key.*\"([^\"]+)\"\s*\n.*$"),),
    "mysql": (re.compile(r"^.*\(1062,.*'([^\']+)'\"\)$"),),
    "ibm_db_sa": (re.compile(r"^.*SQL0803N.*$"),),
}


def _raise_if_duplicate_entry_error(integrity_error, engine_name):
    """Raise exception if two entries are duplicated.

    In this function will be raised DBDuplicateEntry exception if integrity
    error wrap unique constraint violation.
    """

    def get_columns_from_uniq_cons_or_name(columns):
        # note(vsergeyev): UniqueConstraint name convention: "uniq_t0c10c2"
        #                  where `t` it is table name and columns `c1`, `c2`
        #                  are in UniqueConstraint.
        uniqbase = "uniq_"
        if not columns.startswith(uniqbase):
            if engine_name == "postgresql":
                return [columns[columns.index("_") + 1:columns.rindex("_")]]
            return [columns]
        return columns[len(uniqbase):].split("0")[1:]

    if engine_name not in ["ibm_db_sa", "mysql", "sqlite", "postgresql"]:
        return

    # FIXME(johannes): The usage of the .message attribute has been
    # deprecated since Python 2.6. However, the exceptions raised by
    # SQLAlchemy can differ when using unicode() and accessing .message.
    # An audit across all three supported engines will be necessary to
    # ensure there are no regressions.
    for pattern in _DUP_KEY_RE_DB[engine_name]:
        match = pattern.match(integrity_error.message)
        if match:
            break
    else:
        return

    # NOTE(mriedem): The ibm_db_sa integrity error message doesn't provide the
    # columns so we have to omit that from the DBDuplicateEntry error.
    columns = ''

    if engine_name != 'ibm_db_sa':
        columns = match.group(1)

    if engine_name == "sqlite":
        columns = [c.split('.')[-1] for c in columns.strip().split(", ")]
    else:
        columns = get_columns_from_uniq_cons_or_name(columns)
    raise exception.DBDuplicateEntry(columns, integrity_error)


# NOTE(comstud): In current versions of DB backends, Deadlock violation
# messages follow the structure:
#
# mysql:
# (OperationalError) (1213, 'Deadlock found when trying to get lock; try '
#                     'restarting transaction') <query_str> <query_args>
_DEADLOCK_RE_DB = {
    "mysql": re.compile(r"^.*\(1213, 'Deadlock.*")
}


def _raise_if_deadlock_error(operational_error, engine_name):
    """Raise exception on deadlock condition.

    Raise DBDeadlock exception if OperationalError contains a Deadlock
    condition.
    """
    re = _DEADLOCK_RE_DB.get(engine_name)
    if re is None:
        return
    # FIXME(johannes): The usage of the .message attribute has been
    # deprecated since Python 2.6. However, the exceptions raised by
    # SQLAlchemy can differ when using unicode() and accessing .message.
    # An audit across all three supported engines will be necessary to
    # ensure there are no regressions.
    m = re.match(operational_error.message)
    if not m:
        return
    raise exception.DBDeadlock(operational_error)


def _wrap_db_error(f):
    #TODO(rpodolyaka): in a subsequent commit make this a class decorator to
    # ensure it can only applied to Session subclasses instances (as we use
    # Session instance bind attribute below)

    @functools.wraps(f)
    def _wrap(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except UnicodeEncodeError:
            raise exception.DBInvalidUnicodeParameter()
        except sqla_exc.OperationalError as e:
            _raise_if_db_connection_lost(e, self.bind)
            _raise_if_deadlock_error(e, self.bind.dialect.name)
            # NOTE(comstud): A lot of code is checking for OperationalError
            # so let's not wrap it for now.
            raise
        # note(boris-42): We should catch unique constraint violation and
        # wrap it by our own DBDuplicateEntry exception. Unique constraint
        # violation is wrapped by IntegrityError.
        except sqla_exc.IntegrityError as e:
            # note(boris-42): SqlAlchemy doesn't unify errors from different
            # DBs so we must do this. Also in some tables (for example
            # instance_types) there are more than one unique constraint. This
            # means we should get names of columns, which values violate
            # unique constraint, from error message.
            _raise_if_duplicate_entry_error(e, self.bind.dialect.name)
            raise exception.DBError(e)
        except exception.DBError:
            # note(zzzeek) - if _wrap_db_error is applied to nested functions,
            # ensure an existing DBError is propagated outwards
            raise
        except Exception as e:
            LOG.exception(_LE('DB exception wrapped.'))
            raise exception.DBError(e)
    return _wrap


def _synchronous_switch_listener(dbapi_conn, connection_rec):
    """Switch sqlite connections to non-synchronous mode."""
    dbapi_conn.execute("PRAGMA synchronous = OFF")


def _add_regexp_listener(dbapi_con, con_record):
    """Add REGEXP function to sqlite connections."""

    def regexp(expr, item):
        reg = re.compile(expr)
        return reg.search(six.text_type(item)) is not None
    dbapi_con.create_function('regexp', 2, regexp)


def _thread_yield(dbapi_con, con_record):
    """Ensure other greenthreads get a chance to be executed.

    If we use eventlet.monkey_patch(), eventlet.greenthread.sleep(0) will
    execute instead of time.sleep(0).
    Force a context switch. With common database backends (eg MySQLdb and
    sqlite), there is no implicit yield caused by network I/O since they are
    implemented by C libraries that eventlet cannot monkey patch.
    """
    time.sleep(0)


def _ping_listener(engine, dbapi_conn, connection_rec, connection_proxy):
    """Ensures that MySQL and DB2 connections are alive.

    Borrowed from:
    http://groups.google.com/group/sqlalchemy/msg/a4ce563d802c929f
    """
    cursor = dbapi_conn.cursor()
    try:
        ping_sql = 'select 1'
        if engine.name == 'ibm_db_sa':
            # DB2 requires a table expression
            ping_sql = 'select 1 from (values (1)) AS t1'
        cursor.execute(ping_sql)
    except Exception as ex:
        if engine.dialect.is_disconnect(ex, dbapi_conn, cursor):
            msg = _LW('Database server has gone away: %s') % ex
            LOG.warning(msg)
            raise sqla_exc.DisconnectionError(msg)
        else:
            raise


def _set_mode_traditional(dbapi_con, connection_rec, connection_proxy):
    """Set engine mode to 'traditional'.

    Required to prevent silent truncates at insert or update operations
    under MySQL. By default MySQL truncates inserted string if it longer
    than a declared field just with warning. That is fraught with data
    corruption.
    """
    _set_session_sql_mode(dbapi_con, connection_rec,
                          connection_proxy, 'TRADITIONAL')


def _set_session_sql_mode(dbapi_con, connection_rec,
                          connection_proxy, sql_mode=None):
    """Set the sql_mode session variable.

    MySQL supports several server modes. The default is None, but sessions
    may choose to enable server modes like TRADITIONAL, ANSI,
    several STRICT_* modes and others.

    Note: passing in '' (empty string) for sql_mode clears
    the SQL mode for the session, overriding a potentially set
    server default. Passing in None (the default) makes this
    a no-op, meaning if a server-side SQL mode is set, it still applies.
    """
    cursor = dbapi_con.cursor()
    if sql_mode is not None:
        cursor.execute("SET SESSION sql_mode = %s", [sql_mode])

    # Check against the real effective SQL mode. Even when unset by
    # our own config, the server may still be operating in a specific
    # SQL mode as set by the server configuration
    cursor.execute("SHOW VARIABLES LIKE 'sql_mode'")
    row = cursor.fetchone()
    if row is None:
        LOG.warning(_LW('Unable to detect effective SQL mode'))
        return
    realmode = row[1]
    LOG.info(_LI('MySQL server mode set to %s') % realmode)
    # 'TRADITIONAL' mode enables several other modes, so
    # we need a substring match here
    if not ('TRADITIONAL' in realmode.upper() or
            'STRICT_ALL_TABLES' in realmode.upper()):
        LOG.warning(_LW("MySQL SQL mode is '%s', "
                        "consider enabling TRADITIONAL or STRICT_ALL_TABLES")
                    % realmode)


def _is_db_connection_error(args):
    """Return True if error in connecting to db."""
    # NOTE(adam_g): This is currently MySQL specific and needs to be extended
    #               to support Postgres and others.
    # For the db2, the error code is -30081 since the db2 is still not ready
    conn_err_codes = ('2002', '2003', '2006', '2013', '-30081')
    for err_code in conn_err_codes:
        if args.find(err_code) != -1:
            return True
    return False


def _raise_if_db_connection_lost(error, engine):
    # NOTE(vsergeyev): Function is_disconnect(e, connection, cursor)
    #                  requires connection and cursor in incoming parameters,
    #                  but we have no possibility to create connection if DB
    #                  is not available, so in such case reconnect fails.
    #                  But is_disconnect() ignores these parameters, so it
    #                  makes sense to pass to function None as placeholder
    #                  instead of connection and cursor.
    if engine.dialect.is_disconnect(error, None, None):
        raise exception.DBConnectionError(error)


def create_engine(sql_connection, sqlite_fk=False, mysql_sql_mode=None,
                  mysql_traditional_mode=False, idle_timeout=3600,
                  connection_debug=0, max_pool_size=None, max_overflow=None,
                  pool_timeout=None, sqlite_synchronous=True,
                  connection_trace=False, max_retries=10, retry_interval=10):
    """Return a new SQLAlchemy engine."""

    connection_dict = sqlalchemy.engine.url.make_url(sql_connection)

    engine_args = {
        "pool_recycle": idle_timeout,
        'convert_unicode': True,
    }

    logger = logging.getLogger('sqlalchemy.engine')

    # Map SQL debug level to Python log level
    if connection_debug >= 100:
        logger.setLevel(logging.DEBUG)
    elif connection_debug >= 50:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)

    if "sqlite" in connection_dict.drivername:
        if sqlite_fk:
            engine_args["listeners"] = [SqliteForeignKeysListener()]
        engine_args["poolclass"] = NullPool

        if sql_connection == "sqlite://":
            engine_args["poolclass"] = StaticPool
            engine_args["connect_args"] = {'check_same_thread': False}
    else:
        if max_pool_size is not None:
            engine_args['pool_size'] = max_pool_size
        if max_overflow is not None:
            engine_args['max_overflow'] = max_overflow
        if pool_timeout is not None:
            engine_args['pool_timeout'] = pool_timeout

    engine = sqlalchemy.create_engine(sql_connection, **engine_args)

    sqlalchemy.event.listen(engine, 'checkin', _thread_yield)

    if engine.name in ['mysql', 'ibm_db_sa']:
        ping_callback = functools.partial(_ping_listener, engine)
        sqlalchemy.event.listen(engine, 'checkout', ping_callback)
        if engine.name == 'mysql':
            if mysql_traditional_mode:
                mysql_sql_mode = 'TRADITIONAL'
            if mysql_sql_mode:
                mode_callback = functools.partial(_set_session_sql_mode,
                                                  sql_mode=mysql_sql_mode)
                sqlalchemy.event.listen(engine, 'checkout', mode_callback)
    elif 'sqlite' in connection_dict.drivername:
        if not sqlite_synchronous:
            sqlalchemy.event.listen(engine, 'connect',
                                    _synchronous_switch_listener)
        sqlalchemy.event.listen(engine, 'connect', _add_regexp_listener)

    if connection_trace and engine.dialect.dbapi.__name__ == 'MySQLdb':
        _patch_mysqldb_with_stacktrace_comments()

    try:
        engine.connect()
    except sqla_exc.OperationalError as e:
        if not _is_db_connection_error(e.args[0]):
            raise

        remaining = max_retries
        if remaining == -1:
            remaining = 'infinite'
        while True:
            msg = _LW('SQL connection failed. %s attempts left.')
            LOG.warning(msg % remaining)
            if remaining != 'infinite':
                remaining -= 1
            time.sleep(retry_interval)
            try:
                engine.connect()
                break
            except sqla_exc.OperationalError as e:
                if (remaining != 'infinite' and remaining == 0) or \
                        not _is_db_connection_error(e.args[0]):
                    raise
    return engine


class Query(sqlalchemy.orm.query.Query):
    """Subclass of sqlalchemy.query with soft_delete() method."""
    def soft_delete(self, synchronize_session='evaluate'):
        return self.update({'deleted': literal_column('id'),
                            'updated_at': literal_column('updated_at'),
                            'deleted_at': timeutils.utcnow()},
                           synchronize_session=synchronize_session)


class Session(sqlalchemy.orm.session.Session):
    """Custom Session class to avoid SqlAlchemy Session monkey patching."""
    @_wrap_db_error
    def query(self, *args, **kwargs):
        return super(Session, self).query(*args, **kwargs)

    @_wrap_db_error
    def flush(self, *args, **kwargs):
        return super(Session, self).flush(*args, **kwargs)

    @_wrap_db_error
    def execute(self, *args, **kwargs):
        return super(Session, self).execute(*args, **kwargs)

    @_wrap_db_error
    def commit(self, *args, **kwargs):
        return super(Session, self).commit(*args, **kwargs)


def get_maker(engine, autocommit=True, expire_on_commit=False):
    """Return a SQLAlchemy sessionmaker using the given engine."""
    return sqlalchemy.orm.sessionmaker(bind=engine,
                                       class_=Session,
                                       autocommit=autocommit,
                                       expire_on_commit=expire_on_commit,
                                       query_cls=Query)


def _patch_mysqldb_with_stacktrace_comments():
    """Adds current stack trace as a comment in queries.

    Patches MySQLdb.cursors.BaseCursor._do_query.
    """
    import MySQLdb.cursors
    import traceback

    old_mysql_do_query = MySQLdb.cursors.BaseCursor._do_query

    def _do_query(self, q):
        stack = ''
        for filename, line, method, function in traceback.extract_stack():
            # exclude various common things from trace
            if filename.endswith('session.py') and method == '_do_query':
                continue
            if filename.endswith('api.py') and method == 'wrapper':
                continue
            if filename.endswith('utils.py') and method == '_inner':
                continue
            if filename.endswith('exception.py') and method == '_wrap':
                continue
            # db/api is just a wrapper around db/sqlalchemy/api
            if filename.endswith('db/api.py'):
                continue
            # only trace inside nova
            index = filename.rfind('nova')
            if index == -1:
                continue
            stack += "File:%s:%s Method:%s() Line:%s | " \
                     % (filename[index:], line, method, function)

        # strip trailing " | " from stack
        if stack:
            stack = stack[:-3]
            qq = "%s /* %s */" % (q, stack)
        else:
            qq = q
        old_mysql_do_query(self, qq)

    setattr(MySQLdb.cursors.BaseCursor, '_do_query', _do_query)


class EngineFacade(object):
    """A helper class for removing of global engine instances from nova.db.

    As a library, nova.db can't decide where to store/when to create engine
    and sessionmaker instances, so this must be left for a target application.

    On the other hand, in order to simplify the adoption of nova.db changes,
    we'll provide a helper class, which creates engine and sessionmaker
    on its instantiation and provides get_engine()/get_session() methods
    that are compatible with corresponding utility functions that currently
    exist in target projects, e.g. in Nova.

    engine/sessionmaker instances will still be global (and they are meant to
    be global), but they will be stored in the app context, rather that in the
    nova.db context.

    Note: using of this helper is completely optional and you are encouraged to
    integrate engine/sessionmaker instances into your apps any way you like
    (e.g. one might want to bind a session to a request context). Two important
    things to remember:
        1. An Engine instance is effectively a pool of DB connections, so it's
           meant to be shared (and it's thread-safe).
        2. A Session instance is not meant to be shared and represents a DB
           transactional context (i.e. it's not thread-safe). sessionmaker is
           a factory of sessions.

    """

    def __init__(self, sql_connection,
                 sqlite_fk=False, mysql_sql_mode=None,
                 autocommit=True, expire_on_commit=False, **kwargs):
        """Initialize engine and sessionmaker instances.

        :param sqlite_fk: enable foreign keys in SQLite
        :type sqlite_fk: bool

        :param mysql_sql_mode: set SQL mode in MySQL
        :type mysql_sql_mode: string

        :param autocommit: use autocommit mode for created Session instances
        :type autocommit: bool

        :param expire_on_commit: expire session objects on commit
        :type expire_on_commit: bool

        Keyword arguments:

        :keyword idle_timeout: timeout before idle sql connections are reaped
                               (defaults to 3600)
        :keyword connection_debug: verbosity of SQL debugging information.
                                   0=None, 100=Everything (defaults to 0)
        :keyword max_pool_size: maximum number of SQL connections to keep open
                                in a pool (defaults to SQLAlchemy settings)
        :keyword max_overflow: if set, use this value for max_overflow with
                               sqlalchemy (defaults to SQLAlchemy settings)
        :keyword pool_timeout: if set, use this value for pool_timeout with
                               sqlalchemy (defaults to SQLAlchemy settings)
        :keyword sqlite_synchronous: if True, SQLite uses synchronous mode
                                     (defaults to True)
        :keyword connection_trace: add python stack traces to SQL as comment
                                   strings (defaults to False)
        :keyword max_retries: maximum db connection retries during startup.
                              (setting -1 implies an infinite retry count)
                              (defaults to 10)
        :keyword retry_interval: interval between retries of opening a sql
                                 connection (defaults to 10)

        """

        super(EngineFacade, self).__init__()

        self._engine = create_engine(
            sql_connection=sql_connection,
            sqlite_fk=sqlite_fk,
            mysql_sql_mode=mysql_sql_mode,
            idle_timeout=kwargs.get('idle_timeout', 3600),
            connection_debug=kwargs.get('connection_debug', 0),
            max_pool_size=kwargs.get('max_pool_size'),
            max_overflow=kwargs.get('max_overflow'),
            pool_timeout=kwargs.get('pool_timeout'),
            sqlite_synchronous=kwargs.get('sqlite_synchronous', True),
            connection_trace=kwargs.get('connection_trace', False),
            max_retries=kwargs.get('max_retries', 10),
            retry_interval=kwargs.get('retry_interval', 10))
        self._session_maker = get_maker(
            engine=self._engine,
            autocommit=autocommit,
            expire_on_commit=expire_on_commit)

    def get_engine(self):
        """Get the engine instance (note, that it's shared)."""

        return self._engine

    def get_session(self, **kwargs):
        """Get a Session instance.

        If passed, keyword arguments values override the ones used when the
        sessionmaker instance was created.

        :keyword autocommit: use autocommit mode for created Session instances
        :type autocommit: bool

        :keyword expire_on_commit: expire session objects on commit
        :type expire_on_commit: bool

        """

        for arg in kwargs:
            if arg not in ('autocommit', 'expire_on_commit'):
                del kwargs[arg]

        return self._session_maker(**kwargs)
