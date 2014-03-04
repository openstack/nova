# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

Initializing:

* Call set_defaults with the minimal of the following kwargs:
    sql_connection, sqlite_db

  Example:

    session.set_defaults(
        sql_connection="sqlite:///var/lib/nova/sqlite.db",
        sqlite_db="/var/lib/nova/sqlite.db")

Recommended ways to use sessions within this framework:

* Don't use them explicitly; this is like running with AUTOCOMMIT=1.
  model_query() will implicitly use a session when called without one
  supplied. This is the ideal situation because it will allow queries
  to be automatically retried if the database connection is interrupted.

    Note: Automatic retry will be enabled in a future patch.

  It is generally fine to issue several queries in a row like this. Even though
  they may be run in separate transactions and/or separate sessions, each one
  will see the data from the prior calls. If needed, undo- or rollback-like
  functionality should be handled at a logical level. For an example, look at
  the code around quotas and reservation_rollback().

  Examples:

    def get_foo(context, foo):
        return model_query(context, models.Foo).\
                filter_by(foo=foo).\
                first()

    def update_foo(context, id, newfoo):
        model_query(context, models.Foo).\
                filter_by(id=id).\
                update({'foo': newfoo})

    def create_foo(context, values):
        foo_ref = models.Foo()
        foo_ref.update(values)
        foo_ref.save()
        return foo_ref


* Within the scope of a single method, keeping all the reads and writes within
  the context managed by a single session. In this way, the session's __exit__
  handler will take care of calling flush() and commit() for you.
  If using this approach, you should not explicitly call flush() or commit().
  Any error within the context of the session will cause the session to emit
  a ROLLBACK. If the connection is dropped before this is possible, the
  database will implicitly rollback the transaction.

     Note: statements in the session scope will not be automatically retried.

  If you create models within the session, they need to be added, but you
  do not need to call model.save()

    def create_many_foo(context, foos):
        session = get_session()
        with session.begin():
            for foo in foos:
                foo_ref = models.Foo()
                foo_ref.update(foo)
                session.add(foo_ref)

    def update_bar(context, foo_id, newbar):
        session = get_session()
        with session.begin():
            foo_ref = model_query(context, models.Foo, session).\
                        filter_by(id=foo_id).\
                        first()
            model_query(context, models.Bar, session).\
                        filter_by(id=foo_ref['bar_id']).\
                        update({'bar': newbar})

  Note: update_bar is a trivially simple example of using "with session.begin".
  Whereas create_many_foo is a good example of when a transaction is needed,
  it is always best to use as few queries as possible. The two queries in
  update_bar can be better expressed using a single query which avoids
  the need for an explicit transaction. It can be expressed like so:

    def update_bar(context, foo_id, newbar):
        subq = model_query(context, models.Foo.id).\
                filter_by(id=foo_id).\
                limit(1).\
                subquery()
        model_query(context, models.Bar).\
                filter_by(id=subq.as_scalar()).\
                update({'bar': newbar})

  For reference, this emits approximagely the following SQL statement:

    UPDATE bar SET bar = ${newbar}
        WHERE id=(SELECT bar_id FROM foo WHERE id = ${foo_id} LIMIT 1);

* Passing an active session between methods. Sessions should only be passed
  to private methods. The private method must use a subtransaction; otherwise
  SQLAlchemy will throw an error when you call session.begin() on an existing
  transaction. Public methods should not accept a session parameter and should
  not be involved in sessions within the caller's scope.

  Note that this incurs more overhead in SQLAlchemy than the above means
  due to nesting transactions, and it is not possible to implicitly retry
  failed database operations when using this approach.

  This also makes code somewhat more difficult to read and debug, because a
  single database transaction spans more than one method. Error handling
  becomes less clear in this situation. When this is needed for code clarity,
  it should be clearly documented.

    def myfunc(foo):
        session = get_session()
        with session.begin():
            # do some database things
            bar = _private_func(foo, session)
        return bar

    def _private_func(foo, session=None):
        if not session:
            session = get_session()
        with session.begin(subtransaction=True):
            # do some other database things
        return bar


There are some things which it is best to avoid:

* Don't keep a transaction open any longer than necessary.

  This means that your "with session.begin()" block should be as short
  as possible, while still containing all the related calls for that
  transaction.

* Avoid "with_lockmode('UPDATE')" when possible.

  In MySQL/InnoDB, when a "SELECT ... FOR UPDATE" query does not match
  any rows, it will take a gap-lock. This is a form of write-lock on the
  "gap" where no rows exist, and prevents any other writes to that space.
  This can effectively prevent any INSERT into a table by locking the gap
  at the end of the index. Similar problems will occur if the SELECT FOR UPDATE
  has an overly broad WHERE clause, or doesn't properly use an index.

  One idea proposed at ODS Fall '12 was to use a normal SELECT to test the
  number of rows matching a query, and if only one row is returned,
  then issue the SELECT FOR UPDATE.

  The better long-term solution is to use INSERT .. ON DUPLICATE KEY UPDATE.
  However, this can not be done until the "deleted" columns are removed and
  proper UNIQUE constraints are added to the tables.


Enabling soft deletes:

* To use/enable soft-deletes, the SoftDeleteMixin must be added
  to your model class. For example:

      class NovaBase(models.SoftDeleteMixin, models.ModelBase):
          pass


Efficient use of soft deletes:

* There are two possible ways to mark a record as deleted:
    model.soft_delete() and query.soft_delete().

  model.soft_delete() method works with single already fetched entry.
  query.soft_delete() makes only one db request for all entries that correspond
  to query.

* In almost all cases you should use query.soft_delete(). Some examples:

        def soft_delete_bar():
            count = model_query(BarModel).find(some_condition).soft_delete()
            if count == 0:
                raise Exception("0 entries were soft deleted")

        def complex_soft_delete_with_synchronization_bar(session=None):
            if session is None:
                session = get_session()
            with session.begin(subtransactions=True):
                count = model_query(BarModel).\
                            find(some_condition).\
                            soft_delete(synchronize_session=True)
                            # Here synchronize_session is required, because we
                            # don't know what is going on in outer session.
                if count == 0:
                    raise Exception("0 entries were soft deleted")

* There is only one situation where model.soft_delete() is appropriate: when
  you fetch a single record, work with it, and mark it as deleted in the same
  transaction.

        def soft_delete_bar_model():
            session = get_session()
            with session.begin():
                bar_ref = model_query(BarModel).find(some_condition).first()
                # Work with bar_ref
                bar_ref.soft_delete(session=session)

  However, if you need to work with all entries that correspond to query and
  then soft delete them you should use query.soft_delete() method:

        def soft_delete_multi_models():
            session = get_session()
            with session.begin():
                query = model_query(BarModel, session=session).\
                            find(some_condition)
                model_refs = query.all()
                # Work with model_refs
                query.soft_delete(synchronize_session=False)
                # synchronize_session=False should be set if there is no outer
                # session and these entries are not used after this.

  When working with many rows, it is very important to use query.soft_delete,
  which issues a single query. Using model.soft_delete(), as in the following
  example, is very inefficient.

        for bar_ref in bar_refs:
            bar_ref.soft_delete(session=session)
        # This will produce count(bar_refs) db requests.
"""

import os.path
import re
import time

from eventlet import greenthread
from oslo.config import cfg
import six
from sqlalchemy import exc as sqla_exc
import sqlalchemy.interfaces
from sqlalchemy.interfaces import PoolListener
import sqlalchemy.orm
from sqlalchemy.pool import NullPool, StaticPool
from sqlalchemy.sql.expression import literal_column

from nova.openstack.common.db import exception
from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

sqlite_db_opts = [
    cfg.StrOpt('sqlite_db',
               default='nova.sqlite',
               help='the filename to use with sqlite'),
    cfg.BoolOpt('sqlite_synchronous',
                default=True,
                help='If true, use synchronous mode for sqlite'),
]

database_opts = [
    cfg.StrOpt('connection',
               default='sqlite:///' +
                       os.path.abspath(os.path.join(os.path.dirname(__file__),
                       '../', '$sqlite_db')),
               help='The SQLAlchemy connection string used to connect to the '
                    'database',
               deprecated_opts=[cfg.DeprecatedOpt('sql_connection',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sql_connection',
                                                  group='DATABASE')],
               secret=True),
    cfg.StrOpt('slave_connection',
               default='',
               help='The SQLAlchemy connection string used to connect to the '
                    'slave database',
               secret=True),
    cfg.IntOpt('idle_timeout',
               default=3600,
               deprecated_opts=[cfg.DeprecatedOpt('sql_idle_timeout',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sql_idle_timeout',
                                                  group='DATABASE')],
               help='timeout before idle sql connections are reaped'),
    cfg.IntOpt('min_pool_size',
               default=1,
               deprecated_opts=[cfg.DeprecatedOpt('sql_min_pool_size',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sql_min_pool_size',
                                                  group='DATABASE')],
               help='Minimum number of SQL connections to keep open in a '
                    'pool'),
    cfg.IntOpt('max_pool_size',
               default=None,
               deprecated_opts=[cfg.DeprecatedOpt('sql_max_pool_size',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sql_max_pool_size',
                                                  group='DATABASE')],
               help='Maximum number of SQL connections to keep open in a '
                    'pool'),
    cfg.IntOpt('max_retries',
               default=10,
               deprecated_opts=[cfg.DeprecatedOpt('sql_max_retries',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sql_max_retries',
                                                  group='DATABASE')],
               help='maximum db connection retries during startup. '
                    '(setting -1 implies an infinite retry count)'),
    cfg.IntOpt('retry_interval',
               default=10,
               deprecated_opts=[cfg.DeprecatedOpt('sql_retry_interval',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('reconnect_interval',
                                                  group='DATABASE')],
               help='interval between retries of opening a sql connection'),
    cfg.IntOpt('max_overflow',
               default=None,
               deprecated_opts=[cfg.DeprecatedOpt('sql_max_overflow',
                                                  group='DEFAULT'),
                                cfg.DeprecatedOpt('sqlalchemy_max_overflow',
                                                  group='DATABASE')],
               help='If set, use this value for max_overflow with sqlalchemy'),
    cfg.IntOpt('connection_debug',
               default=0,
               deprecated_opts=[cfg.DeprecatedOpt('sql_connection_debug',
                                                  group='DEFAULT')],
               help='Verbosity of SQL debugging information. 0=None, '
                    '100=Everything'),
    cfg.BoolOpt('connection_trace',
                default=False,
                deprecated_opts=[cfg.DeprecatedOpt('sql_connection_trace',
                                                   group='DEFAULT')],
                help='Add python stack traces to SQL as comment strings'),
    cfg.IntOpt('pool_timeout',
               default=None,
               deprecated_opts=[cfg.DeprecatedOpt('sqlalchemy_pool_timeout',
                                                  group='DATABASE')],
               help='If set, use this value for pool_timeout with sqlalchemy'),
]

CONF = cfg.CONF
CONF.register_opts(sqlite_db_opts)
CONF.register_opts(database_opts, 'database')

LOG = logging.getLogger(__name__)

_ENGINE = None
_MAKER = None
_SLAVE_ENGINE = None
_SLAVE_MAKER = None


def set_defaults(sql_connection, sqlite_db, max_pool_size=None,
                 max_overflow=None, pool_timeout=None):
    """Set defaults for configuration variables."""
    cfg.set_defaults(database_opts,
                     connection=sql_connection)
    cfg.set_defaults(sqlite_db_opts,
                     sqlite_db=sqlite_db)
    # Update the QueuePool defaults
    if max_pool_size is not None:
        cfg.set_defaults(database_opts,
                         max_pool_size=max_pool_size)
    if max_overflow is not None:
        cfg.set_defaults(database_opts,
                         max_overflow=max_overflow)
    if pool_timeout is not None:
        cfg.set_defaults(database_opts,
                         pool_timeout=pool_timeout)


def cleanup():
    global _ENGINE, _MAKER
    global _SLAVE_ENGINE, _SLAVE_MAKER

    if _MAKER:
        _MAKER.close_all()
        _MAKER = None
    if _ENGINE:
        _ENGINE.dispose()
        _ENGINE = None
    if _SLAVE_MAKER:
        _SLAVE_MAKER.close_all()
        _SLAVE_MAKER = None
    if _SLAVE_ENGINE:
        _SLAVE_ENGINE.dispose()
        _SLAVE_ENGINE = None


class SqliteForeignKeysListener(PoolListener):
    """Ensures that the foreign key constraints are enforced in SQLite.

    The foreign key constraints are disabled by default in SQLite,
    so the foreign key constraints will be enabled here for every
    database connection
    """
    def connect(self, dbapi_con, con_record):
        dbapi_con.execute('pragma foreign_keys=ON')


def get_session(autocommit=True, expire_on_commit=False,
                sqlite_fk=False, slave_session=False):
    """Return a SQLAlchemy session."""
    global _MAKER
    global _SLAVE_MAKER
    maker = _MAKER

    if slave_session:
        maker = _SLAVE_MAKER

    if maker is None:
        engine = get_engine(sqlite_fk=sqlite_fk, slave_engine=slave_session)
        maker = get_maker(engine, autocommit, expire_on_commit)

    if slave_session:
        _SLAVE_MAKER = maker
    else:
        _MAKER = maker

    session = maker()
    return session


# note(boris-42): In current versions of DB backends unique constraint
# violation messages follow the structure:
#
# sqlite:
# 1 column - (IntegrityError) column c1 is not unique
# N columns - (IntegrityError) column c1, c2, ..., N are not unique
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
_DUP_KEY_RE_DB = {
    "sqlite": re.compile(r"^.*columns?([^)]+)(is|are)\s+not\s+unique$"),
    "postgresql": re.compile(r"^.*duplicate\s+key.*\"([^\"]+)\"\s*\n.*$"),
    "mysql": re.compile(r"^.*\(1062,.*'([^\']+)'\"\)$")
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

    if engine_name not in ["mysql", "sqlite", "postgresql"]:
        return

    m = _DUP_KEY_RE_DB[engine_name].match(integrity_error.message)
    if not m:
        return
    columns = m.group(1)

    if engine_name == "sqlite":
        columns = columns.strip().split(", ")
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
    m = re.match(operational_error.message)
    if not m:
        return
    raise exception.DBDeadlock(operational_error)


def _wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except UnicodeEncodeError:
            raise exception.DBInvalidUnicodeParameter()
        # note(boris-42): We should catch unique constraint violation and
        # wrap it by our own DBDuplicateEntry exception. Unique constraint
        # violation is wrapped by IntegrityError.
        except sqla_exc.OperationalError as e:
            _raise_if_deadlock_error(e, get_engine().name)
            # NOTE(comstud): A lot of code is checking for OperationalError
            # so let's not wrap it for now.
            raise
        except sqla_exc.IntegrityError as e:
            # note(boris-42): SqlAlchemy doesn't unify errors from different
            # DBs so we must do this. Also in some tables (for example
            # instance_types) there are more than one unique constraint. This
            # means we should get names of columns, which values violate
            # unique constraint, from error message.
            _raise_if_duplicate_entry_error(e, get_engine().name)
            raise exception.DBError(e)
        except Exception as e:
            LOG.exception(_('DB exception wrapped.'))
            raise exception.DBError(e)
    _wrap.func_name = f.func_name
    return _wrap


def get_engine(sqlite_fk=False, slave_engine=False):
    """Return a SQLAlchemy engine."""
    global _ENGINE
    global _SLAVE_ENGINE
    engine = _ENGINE
    db_uri = CONF.database.connection

    if slave_engine:
        engine = _SLAVE_ENGINE
        db_uri = CONF.database.slave_connection

    if engine is None:
        engine = create_engine(db_uri,
                               sqlite_fk=sqlite_fk)
    if slave_engine:
        _SLAVE_ENGINE = engine
    else:
        _ENGINE = engine

    return engine


def _synchronous_switch_listener(dbapi_conn, connection_rec):
    """Switch sqlite connections to non-synchronous mode."""
    dbapi_conn.execute("PRAGMA synchronous = OFF")


def _add_regexp_listener(dbapi_con, con_record):
    """Add REGEXP function to sqlite connections."""

    def regexp(expr, item):
        reg = re.compile(expr)
        return reg.search(six.text_type(item)) is not None
    dbapi_con.create_function('regexp', 2, regexp)


def _greenthread_yield(dbapi_con, con_record):
    """Ensure other greenthreads get a chance to be executed.

    Force a context switch. With common database backends (eg MySQLdb and
    sqlite), there is no implicit yield caused by network I/O since they are
    implemented by C libraries that eventlet cannot monkey patch.
    """
    greenthread.sleep(0)


def _ping_listener(dbapi_conn, connection_rec, connection_proxy):
    """Ensures that MySQL connections checked out of the pool are alive.

    Borrowed from:
    http://groups.google.com/group/sqlalchemy/msg/a4ce563d802c929f
    """
    try:
        dbapi_conn.cursor().execute('select 1')
    except dbapi_conn.OperationalError as ex:
        if ex.args[0] in (2006, 2013, 2014, 2045, 2055):
            LOG.warn(_('Got mysql server has gone away: %s'), ex)
            raise sqla_exc.DisconnectionError("Database server went away")
        else:
            raise


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


def create_engine(sql_connection, sqlite_fk=False):
    """Return a new SQLAlchemy engine."""
    # NOTE(geekinutah): At this point we could be connecting to the normal
    #                   db handle or the slave db handle. Things like
    #                   _wrap_db_error aren't going to work well if their
    #                   backends don't match. Let's check.
    _assert_matching_drivers()
    connection_dict = sqlalchemy.engine.url.make_url(sql_connection)

    engine_args = {
        "pool_recycle": CONF.database.idle_timeout,
        "echo": False,
        'convert_unicode': True,
    }

    # Map our SQL debug level to SQLAlchemy's options
    if CONF.database.connection_debug >= 100:
        engine_args['echo'] = 'debug'
    elif CONF.database.connection_debug >= 50:
        engine_args['echo'] = True

    if "sqlite" in connection_dict.drivername:
        if sqlite_fk:
            engine_args["listeners"] = [SqliteForeignKeysListener()]
        engine_args["poolclass"] = NullPool

        if CONF.database.connection == "sqlite://":
            engine_args["poolclass"] = StaticPool
            engine_args["connect_args"] = {'check_same_thread': False}
    else:
        if CONF.database.max_pool_size is not None:
            engine_args['pool_size'] = CONF.database.max_pool_size
        if CONF.database.max_overflow is not None:
            engine_args['max_overflow'] = CONF.database.max_overflow
        if CONF.database.pool_timeout is not None:
            engine_args['pool_timeout'] = CONF.database.pool_timeout

    engine = sqlalchemy.create_engine(sql_connection, **engine_args)

    sqlalchemy.event.listen(engine, 'checkin', _greenthread_yield)

    if 'mysql' in connection_dict.drivername:
        sqlalchemy.event.listen(engine, 'checkout', _ping_listener)
    elif 'sqlite' in connection_dict.drivername:
        if not CONF.sqlite_synchronous:
            sqlalchemy.event.listen(engine, 'connect',
                                    _synchronous_switch_listener)
        sqlalchemy.event.listen(engine, 'connect', _add_regexp_listener)

    if (CONF.database.connection_trace and
            engine.dialect.dbapi.__name__ == 'MySQLdb'):
        _patch_mysqldb_with_stacktrace_comments()

    try:
        engine.connect()
    except sqla_exc.OperationalError as e:
        if not _is_db_connection_error(e.args[0]):
            raise

        remaining = CONF.database.max_retries
        if remaining == -1:
            remaining = 'infinite'
        while True:
            msg = _('SQL connection failed. %s attempts left.')
            LOG.warn(msg % remaining)
            if remaining != 'infinite':
                remaining -= 1
            time.sleep(CONF.database.retry_interval)
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
        for file, line, method, function in traceback.extract_stack():
            # exclude various common things from trace
            if file.endswith('session.py') and method == '_do_query':
                continue
            if file.endswith('api.py') and method == 'wrapper':
                continue
            if file.endswith('utils.py') and method == '_inner':
                continue
            if file.endswith('exception.py') and method == '_wrap':
                continue
            # db/api is just a wrapper around db/sqlalchemy/api
            if file.endswith('db/api.py'):
                continue
            # only trace inside nova
            index = file.rfind('nova')
            if index == -1:
                continue
            stack += "File:%s:%s Method:%s() Line:%s | " \
                     % (file[index:], line, method, function)

        # strip trailing " | " from stack
        if stack:
            stack = stack[:-3]
            qq = "%s /* %s */" % (q, stack)
        else:
            qq = q
        old_mysql_do_query(self, qq)

    setattr(MySQLdb.cursors.BaseCursor, '_do_query', _do_query)


def _assert_matching_drivers():
    """Make sure slave handle and normal handle have the same driver."""
    # NOTE(geekinutah): There's no use case for writing to one backend and
    #                 reading from another. Who knows what the future holds?
    if CONF.database.slave_connection == '':
        return

    normal = sqlalchemy.engine.url.make_url(CONF.database.connection)
    slave = sqlalchemy.engine.url.make_url(CONF.database.slave_connection)
    assert normal.drivername == slave.drivername
