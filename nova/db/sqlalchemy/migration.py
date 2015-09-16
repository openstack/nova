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

import base64
import os
import random

import alembic.autogenerate
import alembic.migration
import alembic.operations
from migrate import exceptions as versioning_exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning.repository import Repository
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log import log as logging
import sqlalchemy
from sqlalchemy.sql import null

from nova.db.sqlalchemy import api as db_session
from nova.db.sqlalchemy import models
from nova import exception
from nova.i18n import _

INIT_VERSION = {}
INIT_VERSION['main'] = 215
INIT_VERSION['api'] = 0
_REPOSITORY = {}

LOG = logging.getLogger(__name__)


def get_engine(database='main'):
    if database == 'main':
        return db_session.get_engine()
    if database == 'api':
        return db_session.get_api_engine()


def _db_sync_locked(repository):
    engine = get_engine()
    try:
        migrate_version = db_utils.get_table(engine, repository.version_table)
    except sqlalchemy.exc.NoSuchTableError:
        # Table doesn't exist yet, cannot be locked
        return False

    row = sqlalchemy.sql.select([migrate_version]).\
              where(migrate_version.c.repository_id == repository.id).\
              execute().fetchone()
    if not row or 'locked' not in row:
        # 'db expand' will create row if missing and it will add locked
        # column if missing. If 'db expand' hasn't been run, then the
        # repo can't be locked
        return False

    return row['locked']


def _set_db_sync_lock(repository, locked):
    locked = locked and 1 or 0

    engine = get_engine()
    migrate_version = db_utils.get_table(engine, repository.version_table)
    return migrate_version.update().\
            where(migrate_version.c.repository_id == repository.id).\
            values(locked=locked).execute().rowcount


def _set_db_sync_version(repository, version):
    engine = get_engine()
    migrate_version = db_utils.get_table(engine, repository.version_table)
    migrate_version.update().\
            where(migrate_version.c.repository_id == repository.id).\
            values(version=version).execute()


def db_sync(version=None, database='main'):
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.NovaException(_("version should be an integer"))

    current_version = db_version(database)
    repository = _find_migrate_repo(database)

    if _db_sync_locked(repository):
        msg = _("Cannot run 'db sync' until 'db contract' is run")
        raise exception.DatabaseMigrationError(reason=msg)

    if version is None or version > current_version:
        return versioning_api.upgrade(get_engine(database), repository,
                version)
    else:
        return versioning_api.downgrade(get_engine(database), repository,
                version)


def db_version(database='main'):
    repository = _find_migrate_repo(database)
    try:
        return versioning_api.db_version(get_engine(database), repository)
    except versioning_exceptions.DatabaseNotControlledError as exc:
        meta = sqlalchemy.MetaData()
        engine = get_engine(database)
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0:
            db_version_control(INIT_VERSION[database], database)
            return versioning_api.db_version(get_engine(database), repository)
        else:
            LOG.exception(exc)
            # Some pre-Essex DB's may not be version controlled.
            # Require them to upgrade using Essex first.
            raise exception.NovaException(
                _("Upgrade DB using Essex release first."))


def db_initial_version(database='main'):
    return INIT_VERSION[database]


def _ignore_table(name):
    # Anything starting with dump_ is a backup from previous
    # migration scripts.
    return name.startswith('dump_')


def _include_object(object_, name, type_, reflected, compare_to):
    if type_ == 'table':
        return not _ignore_table(name)

    return True


_REFLECT_CACHE = {}


def _compare_type(context, inspector_column, metadata_column,
                  inspector_type, metadata_type):
    # Types can be silently modified on the server side. For instance,
    # under MySQL, the "BOOL" type is an alias to "TINYINT". As a result,
    # creating a column with "BOOL" will reflect as "TINYINT". Instead of
    # manually maintaining a mapping of types per database engine, let's
    # create a temporary table with metadata_type, reflect that, then
    # compare the two reflected values to see if they match.

    # Check with the alembic implementation first. I haven't seen a false
    # negative yet (where it considers the types the same when they really
    # aren't), but there are some false positives dealing with aliasing
    # of types and some metadata.
    if not context.impl.compare_type(inspector_column, metadata_column):
        return False

    key = str(metadata_type)
    reflected_type = _REFLECT_CACHE.get(key)
    if reflected_type is None:
        conn = context.bind.connect()
        tmp_meta = sqlalchemy.MetaData(conn)

        randchars = ''.join(chr(random.randint(0, 255)) for _ in xrange(5))
        tmp_table_name = 'reflect_' + base64.b32encode(randchars).lower()
        tmp_table = sqlalchemy.Table(tmp_table_name, tmp_meta,
                                     sqlalchemy.Column('a', metadata_type),
                                     prefixes=['TEMPORARY'])
        tmp_table.create()

        inspect = sqlalchemy.inspect(conn)
        columns = inspect.get_columns(tmp_table_name)

        tmp_table.drop()

        column_types = {c['name']: c['type'] for c in columns}
        reflected_type = column_types['a']
        _REFLECT_CACHE[key] = reflected_type

    # Now compare the types
    if inspector_type.__class__ is not reflected_type.__class__:
        return True

    # And compare any specific attributes about this type
    # TODO(johannes): This should handle dialect specific attributes
    # (eg charset, collation, etc on MySQL VARCHAR type). This is
    # probably best done in alembic correctly
    for attr in ('length', 'display_width'):
        if (hasattr(inspector_type, attr) and
            getattr(inspector_type, attr) != getattr(reflected_type, attr)):
                return True

    return False


def _create_migration_context(as_sql=False):
    engine = get_engine()
    opts = {
        'include_object': _include_object,
        'compare_type': _compare_type,
        'as_sql': as_sql,
    }
    return alembic.migration.MigrationContext.configure(engine, opts=opts)


class OperationBase(object):
    # Be conservative by default
    desired_phase = 'migrate'
    removes = False

    def __init__(self):
        self.provides = set()
        self.depends = set()
        self.conflicts = set()


class AddTable(OperationBase):
    # Always safe since no old code should be using this table
    desired_phase = 'expand'

    def __init__(self, table):
        super(AddTable, self).__init__()

        self.table = table

        self.provides = set(('column', table.name, c.name)
                            for c in table.columns)

    def execute(self, ddlop):
        # Need to copy columns so they are unlinked from metadata table
        columns = [c.copy() for c in self.table.columns]
        ddlop.create_table(self.table.name, *columns,
                           mysql_engine='InnoDB',
                           mysql_charset='utf8')

    def __repr__(self):
        return '<AddTable table_name=%s>' % self.table.name


class DropTable(OperationBase):
    # Always safe since no new code should be using this table
    desired_phase = 'contract'
    removes = True

    def __init__(self, table):
        super(DropTable, self).__init__()

        self.table = table

        provides = set(('column', table.name, c.name)
                       for c in table.columns)

        # Indexes and constraints are implicitly dropped for a DROP TABLE.
        # Add the indexcol so foreign keys get ordered correctly
        for index in table.indexes:
            column_names = [c.name for c in index.columns]
            provides.add(('indexcol', table.name, column_names[0]))

        for constraint in table.constraints:
            if not isinstance(constraint, (sqlalchemy.UniqueConstraint,
                                           sqlalchemy.PrimaryKeyConstraint)):
                continue

            column_names = [c.name for c in constraint.columns]
            # SQLAlchemy can add a PrimaryKeyConstraint even if one
            # doesn't exist. In that case, column_names will be empty
            if column_names:
                provides.add(('indexcol', table.name, column_names[0]))

        self.provides = provides

    def execute(self, ddlop):
        ddlop.drop_table(self.table.name)

    def __repr__(self):
        return '<DropTable table_name=%r>' % self.table.name


class AddColumn(OperationBase):
    def __init__(self, table_name, column, desired_phase=None):
        super(AddColumn, self).__init__()

        self.table_name = table_name
        self.column = column

        if desired_phase:
            self.desired_phase = desired_phase

        self.provides = set([('column', table_name, column.name)])

    def execute(self, ddlop):
        column = self.column.copy()
        ddlop.add_column(self.table_name, column)

    def __repr__(self):
        return ('<AddColumn column={table_name=%s column_name=%s type=%r}>' %
                (self.table_name, self.column.name, self.column.type))


class AlterColumn(OperationBase):
    def __init__(self, table_name, column_name, args):
        super(AlterColumn, self).__init__()

        self.table_name = table_name
        self.column_name = column_name
        self.args = args

        self.provides = [('column', table_name, column_name)]
        # Cannot alter column with foreign key
        self.conflicts = [('fkcol', table_name, column_name)]

    def execute(self, ddlop):
        ddlop.alter_column(self.table_name, self.column_name, **self.args)

    def __repr__(self):
        return ('<AlterColumn table_name=%s column_name=%s args=%r>' %
                (self.table_name, self.column_name, self.args))


class DropColumn(OperationBase):
    # Always online safe since no new code should be using this column
    desired_phase = 'contract'
    removes = True

    def __init__(self, table_name, column):
        super(DropColumn, self).__init__()

        self.table_name = table_name
        self.column = column

        self.provides = set([('column', table_name, column.name)])

    def execute(self, ddlop):
        ddlop.drop_column(self.table_name, self.column.name)

    def __repr__(self):
        return ('<DropColumn column={table_name=%s column_name=%s}>' %
                (self.table_name, self.column.name))


class AddIndex(OperationBase):
    def __init__(self, index, args):
        super(AddIndex, self).__init__()

        table_name = index.table.name
        column_names = [c.name for c in index.columns]

        self.index = index
        self.args = args

        # Adding a unique index isn't semantically safe since code may
        # not be aware of the new constraint on the column(s).
        self.desired_phase = 'migrate' if index.unique else 'expand'

        self.provides = set([
            ('index', table_name, index.name),
            ('indexcol', table_name, column_names[0]),
        ])
        # Columns need to exist before index is created
        self.depends = set(('column', table_name, name)
                           for name in column_names)

    def execute(self, ddlop):
        name = self.index.name
        table_name = self.index.table.name
        column_names = [c.name for c in self.index.columns]
        ddlop.create_index(name, table_name, column_names,
                           unique=self.index.unique, **self.args)

    def __repr__(self):
        index = self.index
        column_names = [c.name for c in index.columns]
        return ('<AddIndex index={table_name=%s name=%s column_names=(%s)} '
                'args=%r>' % (index.table.name, index.name,
                ', '.join(column_names), self.args))


class DropIndex(OperationBase):
    removes = True

    def __init__(self, index):
        super(DropIndex, self).__init__()

        self.index = index
        # This is used for conflicts
        self.column_names = [c.name for c in index.columns]

        # Removing a unique index should happen in migrate since
        # new code may assume there isn't any restriction anymore.
        self.desired_phase = 'migrate' if index.unique else 'contract'

        table_name = index.table.name

        self.provides = set([
            ('index', table_name, index.name),
            ('indexcol', table_name, self.column_names[0]),
        ])
        # Can't remove an index if there is a FK potentially using it
        self.conflicts = set(('fkcol', table_name, name)
                             for name in self.column_names)

    def execute(self, ddlop):
        ddlop.drop_index(self.index.name, self.index.table.name)

    def __repr__(self):
        index = self.index
        return ('<DropIndex index={table_name=%s name=%s}>' %
                (index.table.name, index.name))


class AddUniqueConstraint(OperationBase):
    def __init__(self, uc, desired_phase=None):
        super(AddUniqueConstraint, self).__init__()

        self.uc = uc
        if desired_phase:
            self.desired_phase = desired_phase

        table = uc.table
        column_names = [c.name for c in uc.columns]

        self.provides = set([
            # So drop_constraint is ordered before against add_uc
            ('uc', table.name, uc.name),
            ('indexcol', table.name, column_names[0]),
        ])
        # Columns need to exist before constraint is created
        self.depends = set(('column', table.name, c.name)
                           for c in uc.columns)

    def execute(self, ddlop):
        uc = self.uc
        table = uc.table
        column_names = [c.name for c in uc.columns]

        ddlop.create_unique_constraint(uc.name, table.name, column_names)

    def __repr__(self):
        uc = self.uc
        column_names = [c.name for c in uc.columns]

        return ('<AddUniqueConstraint uc={name=%s table_name=%s '
                'column_names=(%s)}>' % (uc.name, uc.table.name,
                ', '.join(column_names)))


class DropUniqueConstraint(OperationBase):
    removes = True

    def __init__(self, uc):
        super(DropUniqueConstraint, self).__init__()

        self.uc = uc

        table = uc.table

        # So this gets ordered against Add correctly
        self.provides = set([('uc', table.name, uc.name)])

        # Should be scheduled before any columns dropped
        self.depends = set(('column', table.name, c.name)
                           for c in uc.columns)

    def execute(self, ddlop):
        uc = self.uc
        table = uc.table

        ddlop.drop_constraint(uc.name, table.name, type_='unique')

    def __repr__(self):
        uc = self.uc
        column_names = [c.name for c in uc.columns]

        return ('<DropUniqueConstraint uc={name=%s table_name=%s '
                'column_names=(%s)}>' % (uc.name, uc.table.name,
                ', '.join(column_names)))


class AddForeignKey(OperationBase):
    def __init__(self, fkc, desired_phase=None):
        super(AddForeignKey, self).__init__()

        self.fkc = fkc
        if desired_phase:
            self.desired_phase = desired_phase

        fk = fkc.elements[0]
        src_table_name = fk.parent.table.name
        ref_table_name = fk.column.table.name

        provides = set([('fk', src_table_name, fkc.name)])
        depends = set([
            ('indexcol', src_table_name, fk.parent.name),
            ('indexcol', ref_table_name, fk.column.name),
        ])

        for fk in fkc.elements:
            provides.update([
                ('fkcol', src_table_name, fk.parent.name),
                ('fkcol', ref_table_name, fk.column.name),
            ])
            depends.update([
                ('column', src_table_name, fk.parent.name),
                ('column', ref_table_name, fk.column.name),
            ])

        self.provides = provides
        self.depends = depends

    def execute(self, ddlop):
        fkc = self.fkc

        src_table_name = fkc.elements[0].parent.table.name
        src_column_names = [fk.parent.name for fk in fkc.elements]
        ref_table_name = fkc.elements[0].column.table.name
        ref_column_names = [fk.column.name for fk in fkc.elements]

        ddlop.create_foreign_key(fkc.name,
                                 src_table_name, ref_table_name,
                                 src_column_names, ref_column_names)

    def __repr__(self):
        fkc = self.fkc
        src_table_name = fkc.elements[0].parent.table.name
        src_column_names = [fk.parent.name for fk in fkc.elements]
        ref_table_name = fkc.elements[0].column.table.name
        ref_column_names = [fk.column.name for fk in fkc.elements]

        return ('<AddForeignKey fk={name=%r src_columns=%s.(%s) '
                'ref_columns=%s.(%s)}>' % (fkc.name, src_table_name,
                ', '.join(src_column_names), ref_table_name,
                ', '.join(ref_column_names)))


class DropForeignKey(OperationBase):
    removes = True

    def __init__(self, fkc, desired_phase=None):
        super(DropForeignKey, self).__init__()

        self.fkc = fkc
        if desired_phase:
            self.desired_phase = desired_phase

        fk = fkc.elements[0]
        src_table_name = fk.parent.table.name
        ref_table_name = fk.column.table.name

        provides = set([('fk', src_table_name, fkc.name)])
        depends = set([
            ('indexcol', src_table_name, fk.parent.name),
            ('indexcol', ref_table_name, fk.column.name),
        ])

        for fk in fkc.elements:
            provides.update([
                ('fkcol', src_table_name, fk.parent.name),
                ('fkcol', ref_table_name, fk.column.name),
            ])

        self.provides = provides
        self.depends = depends

    def execute(self, ddlop):
        fkc = self.fkc
        table = fkc.table

        ddlop.drop_constraint(fkc.name, table.name, type_='foreignkey')

    def __repr__(self):
        fkc = self.fkc
        src_table_name = fkc.elements[0].parent.table.name
        src_column_names = [fk.parent.name for fk in fkc.elements]
        ref_table_name = fkc.elements[0].column.table.name
        ref_column_names = [fk.column.name for fk in fkc.elements]

        return ('<DropForeignKey fkc={name=%s src_columns=%s.(%s) '
                'ref_columns=%s.(%s)}>' %
                (fkc.name, src_table_name, ', '.join(src_column_names),
                 ref_table_name, ', '.join(ref_column_names)))


def _table_fk_constraints(table):
    return [c for c in table.constraints
            if isinstance(c, sqlalchemy.ForeignKeyConstraint)]


def _fkc_matches_key(metadata, ckey):
    for table in metadata.tables.values():
        for fkc in _table_fk_constraints(table):
            fk = fkc.elements[0]
            src_table_name = fk.parent.table.name
            ref_table_name = fk.column.table.name

            for fk in fkc.elements:
                for key in [('fkcol', src_table_name, fk.parent.name),
                            ('fkcol', ref_table_name, fk.column.name)]:
                    if key == ckey:
                        yield fkc
                    break


def _compare_fkc(afkc, bfkc):
    # Comparing name is best, but new foreign key constraints might not
    # have a name set yet
    if afkc.name != bfkc.name:
        return False

    afk = afkc.elements[0]
    bfk = bfkc.elements[0]
    if afk.parent.table.name != bfk.parent.table.name:
        return False

    acolumns = [(fk.parent.name, fk.column.name) for fk in afkc.elements]
    bcolumns = [(fk.parent.name, fk.column.name) for fk in bfkc.elements]
    if acolumns != bcolumns:
        return False

    return True


class Converter(object):
    def _handle_add_table(self, table):
        # ('add_table', Table)

        # alembic can take some operations as part of op.create_table()
        # but not all. We also want to separate foreign keys since they
        # can potentially create a dependency on another op we haven't
        # seen yet. As a result, this one diff from alembic might be
        # split up into multiple ops we track and apply in different
        # phases.
        tblop = AddTable(table)
        yield tblop

        for uc in [c for c in table.constraints
                   if isinstance(c, sqlalchemy.UniqueConstraint)]:
            yield AddUniqueConstraint(uc, desired_phase=tblop.desired_phase)

        for fkc in _table_fk_constraints(table):
            yield AddForeignKey(fkc, desired_phase=tblop.desired_phase)

    def _handle_remove_table(self, table):
        # ('remove_table', Table)
        tblop = DropTable(table)
        yield tblop

        for fkc in _table_fk_constraints(table):
            yield DropForeignKey(fkc, desired_phase=tblop.desired_phase)

    def _handle_add_column(self, schema, table_name, column):
        # ('add_column', schema, table_name, Column)

        kwargs = {}
        if table_name == 'migrate_version':
            # The column added to migrate_version needs to exist after the
            # expand phase runs so locking out 'db sync' can happen.
            kwargs['desired_phase'] = 'expand'

        yield AddColumn(table_name, column, **kwargs)

    def _handle_remove_column(self, schema, table_name, column):
        # ('remove_column', schema, table_name, Column)
        yield DropColumn(table_name, column)

    def _handle_add_constraint(self, constraint):
        # ('add_constraint', UniqueConstraint)
        if not isinstance(constraint, sqlalchemy.UniqueConstraint):
            raise ValueError('Unknown constraint type %r' % constraint)

        yield AddUniqueConstraint(constraint)

    def _handle_remove_constraint(self, constraint):
        # ('remove_constraint', Constraint)
        if not isinstance(constraint, sqlalchemy.UniqueConstraint):
            raise ValueError('Unknown constraint type %r' % constraint)

        yield DropUniqueConstraint(constraint)

    def _handle_add_index(self, index):
        # ('add_index', Index)

        # Include any dialect specific options (mysql_length, etc)
        args = {}
        for dialect, options in index.dialect_options.items():
            for k, v in options.items():
                args['%s_%s' % (dialect, k)] = v

        yield AddIndex(index, args)

    def _handle_remove_index(self, index):
        # ('remove_index', Index)
        yield DropIndex(index)

    def _handle_add_fk(self, fkc):
        # ('add_fk', ForeignKeyConstraint)
        yield AddForeignKey(fkc)

    def _handle_remove_fk(self, fkc):
        # ('remove_fk', ForeignKeyConstraint)
        yield DropForeignKey(fkc)

    def _column_changes(self, diffs):
        # Column change (type, nullable, etc)
        table_name = diffs[0][2]
        column_name = diffs[0][3]

        args = {}
        for diff in diffs:
            cmd = diff[0]

            if cmd == 'modify_nullable':
                # ('modify_nullable', None, table_name, column_name,
                #  {'existing_server_default': None,
                #   'existing_type': VARCHAR(length=36)},
                #  conn_nullable, metadata_nullable)
                existing_type = diff[4]['existing_type']
                nullable = diff[6]

                args['existing_type'] = existing_type
                args['nullable'] = nullable
            elif cmd == 'modify_type':
                # ('modify_type', None, table_name, column_name,
                #  {'existing_nullable': True,
                #   'existing_server_default': None},
                #  TINYINT(display_width=1), Boolean())
                existing_nullable = diff[4]['existing_nullable']
                new_type = diff[6]

                if 'nullable' not in args:
                    args['nullable'] = existing_nullable
                args['type_'] = new_type
            else:
                msg = _('Unknown alembic cmd %s') % cmd
                raise exception.DatabaseMigrationError(reason=msg)

        yield AlterColumn(table_name, column_name, args)

    def convert_alembic(self, diffs):
        ops = []
        for diff in diffs:
            # Parse out the format into something easier to use than the
            # tuple/list format that alembic returns

            if isinstance(diff, list):
                ret = self._column_changes(diff)
            else:
                cmd = diff[0]

                handler = getattr(self, '_handle_%s' % cmd, None)
                if handler is None:
                    msg = _('Unknown alembic cmd %s') % cmd
                    raise exception.DatabaseMigrationError(reason=msg)

                ret = handler(*diff[1:])

            ops.extend(list(ret))

        return ops


class Scheduler(object):
    def __init__(self, ops=None):
        # Set of operations (vertexes)
        self.ops = set()
        # Operations that have conflicts to process
        self.conflictops = set()

        # Indirect mapping of operations
        self.exists = {}
        self.nonexists = {}
        # Dependencies and conflicts per op (resolve via mapping)
        self.depends = {}
        self.conflicts = {}

        # Edges per op
        self.outbound = {}
        self.inbound = {}

        if ops is not None:
            for op in ops:
                self.add(op)

    def handle_conflicts(self, metadata):
        # Foreign keys can make certain operations fail. The foreign key
        # needs to be removed before the operation and then recreated
        # after the operation.
        #
        # This finds all foreign keys that currently exist and determines
        # if they could conflict, then it finds any operations that are
        # already in the schedule. If appropriate operations don't exist,
        # then they are created.
        for op in self.conflictops:
            for key in self.conflicts[op]:
                for fkc in _fkc_matches_key(metadata, key):
                    # Find any ops that match this key
                    dropops = self.nonexists.get(key, [])
                    dropops = [op for op in dropops
                               if _compare_fkc(fkc, op.fkc)]

                    addops = self.exists.get(key, [])
                    addops = [op for op in addops
                              if _compare_fkc(fkc, op.fkc)]

                    if not dropops and not addops:
                        # No drop or add operations for this FK,
                        # so create some
                        self.add(DropForeignKey(fkc))
                        self.add(AddForeignKey(fkc))

        # Ensure operation gets scheduled between the drop and add operations
        for op in self.conflictops:
            for key in self.conflicts[op]:
                dropops = self.nonexists.get(key, [])
                addops = self.exists.get(key, [])

                for dropop in dropops:
                    self.add_edge(op, dropop)

                for addop in addops:
                    self.add_edge(addop, op)

    def add(self, op):
        self.ops.add(op)
        self.inbound[op] = set()
        self.outbound[op] = set()

        if op.removes:
            mapping = self.nonexists
        else:
            mapping = self.exists

        for key in op.provides:
            mapping.setdefault(key, set()).add(op)
        self.depends[op] = op.depends

        if op.conflicts:
            self.conflicts[op] = op.conflicts
            self.conflictops.add(op)

    def add_edge(self, f, t):
        self.inbound[t].add(f)
        self.outbound[f].add(t)

    def sort(self):
        # The topological sort modifies inbound, but we can't do a deepcopy
        # since that would deepcopy the key too.
        inbound = {}
        for key, depends in self.inbound.items():
            inbound[key] = set(depends)

        toprocess = [v for v in self.ops if not inbound[v]]
        inorder = []
        while toprocess:
            op = toprocess.pop(0)
            inorder.insert(0, op)

            for depop in self.outbound[op]:
                inbound[depop].remove(op)
                if not inbound[depop]:
                    toprocess.insert(0, depop)

            del inbound[op]

        # Anything remaining in inbound is a dependency loop
        if inbound:
            msg = _('Dependency loop exists in database migrations')
            raise exception.DatabaseMigrationError(reason=msg)

        return inorder

    def order_drop_add(self):
        # Alembic will emit drop/add for indexes if the covered columns change.
        # Ensure that the add is scheduled after the drop.
        keys = set(self.exists.keys()) & set(self.nonexists.keys())
        for key in keys:
            dropops = self.nonexists[key]
            addops = self.exists[key]
            for dropop in dropops:
                for addop in addops:
                    self.add_edge(addop, dropop)

    def schedule(self):
        # Scheduling tries to move as much of the schema changes to be run
        # while services are still running without affecting the services.
        # Otherwise known as running the schema changes online.
        #
        # There are two major factors used:
        # 1) Is the schema change compatible with running code? Adding a new
        #    table is since no code knows about it, but changing a column type
        #    may not be.
        # 2) Does the DDL statement cause the database engine to block access
        #    to the table and affect running services? This can vary greatly
        #    depending on the database software (MySQL, PostgreSQL, etc),
        #    version (5.1, 5.5, 5.6, etc) and the storage engine (MyISAM,
        #    InnoDB, etc)
        #
        # Also, dependencies between operations might keep an operation that
        # would otherwise be safe to be run online from being run online.

        self.order_drop_add()

        # Use mapping to create edges between operations
        for op, depends in self.depends.items():
            if op.removes:
                mapping = self.nonexists
            else:
                mapping = self.exists

            for key in depends:
                refops = mapping.get(key, [])

                for refop in refops:
                    # Dependency is reversed for drop operations
                    if op.removes:
                        self.add_edge(refop, op)
                    else:
                        self.add_edge(op, refop)

        phases = {
            'expand': [],
            'migrate': [],
            'contract': [],
        }

        # TODO(johannes): Schedule operations that are safe to run online
        # depending on the capabilities of the database engine

        for op in self.sort():
            phase = op.desired_phase

            if phase == 'expand':
                depphases = set(o.phase for o in self.outbound[op])
                depphases.discard(phase)
                if depphases:
                    # Can't safely move this operation to expand because
                    # a dependency isn't in expand.
                    phase = 'migrate'
            elif phase == 'contract':
                # Since anything that depends on this hasn't had the
                # phase determined yet, this has to be naive for now
                if self.inbound[op]:
                    phase = 'migrate'

            op.phase = phase
            phases[op.phase].append(op)

        return phases['expand'], phases['migrate'], phases['contract']


def _add_generated_tables_to_model(metadata, database='main'):
    tables = dict(metadata.tables)
    for table_name, table in tables.items():
        if table_name.startswith('shadow_') or _ignore_table(table_name):
            # Don't make a shadow of a shadow table or a table we
            # explicitly ignore
            continue

        shadow_table_name = 'shadow_' + table_name
        if shadow_table_name in tables:
            # Shadow table already exists in model
            continue

        columns = [c.copy() for c in table.columns]
        sqlalchemy.Table(shadow_table_name, metadata, *columns,
                         mysql_engine='InnoDB')
        # Table is added to metadata as a side-effect of creating the object

    repository = _find_migrate_repo(database)
    if repository.version_table not in tables:
        # The existing migrate_version table is expanded with a locked
        # column so the 'db sync' command can be locked out between
        # running 'db expand' and 'db contract'.

        # locked is probably more appropriate a Boolean, but there is no
        # portable way of using server_default in that case. SQLAlchemy
        # issue #1204
        sqlalchemy.Table(repository.version_table, metadata,
                sqlalchemy.Column('repository_id', sqlalchemy.String(250),
                                  primary_key=True),
                sqlalchemy.Column('repository_path', sqlalchemy.Text()),
                sqlalchemy.Column('version', sqlalchemy.Integer()),
                sqlalchemy.Column('locked', sqlalchemy.Integer(),
                                  nullable=False, server_default='0'))
        # Table is added to metadata as a side-effect of creating the object


def _schedule_schema_changes(context):
    """Split the list of diffs into expand, migrate and contract phases."""

    metadata = models.BASE.metadata
    _add_generated_tables_to_model(metadata)

    # Take all of the diffs generated by Alembic and convert them into an
    # easier to use format along with some dependency information.
    diffs = alembic.autogenerate.compare_metadata(context, metadata)

    converter = Converter()
    ops = converter.convert_alembic(diffs)

    scheduler = Scheduler(ops)

    reflected_metadata = sqlalchemy.MetaData()
    reflected_metadata.reflect(context.bind)

    scheduler.handle_conflicts(reflected_metadata)

    return scheduler.schedule()


def db_expand(dryrun=False, database='main'):
    context = _create_migration_context(as_sql=False)
    expand, migrate, contract = _schedule_schema_changes(context)

    context = _create_migration_context(as_sql=dryrun)
    ddlop = alembic.operations.Operations(context)
    for op in expand:
        op.execute(ddlop)

    if not dryrun:
        repository = _find_migrate_repo(database)
        if not _set_db_sync_lock(repository, locked=True):
            # No rows exist yet. Might be 'db sync' was never run
            db_version_control(INIT_VERSION)
            _set_db_sync_lock(repository, locked=True)


def db_migrate(dryrun=False, database='main'):
    context = _create_migration_context(as_sql=False)
    expand, migrate, contract = _schedule_schema_changes(context)

    if expand:
        msg = _('expand phase still has operations that need to be executed')
        raise exception.DatabaseMigrationError(reason=msg)

    context = _create_migration_context(as_sql=dryrun)
    ddlop = alembic.operations.Operations(context)
    for op in migrate:
        op.execute(ddlop)


def db_contract(dryrun=False, database='main'):
    context = _create_migration_context(as_sql=False)
    expand, migrate, contract = _schedule_schema_changes(context)

    if expand:
        msg = _('expand phase still has operations that need to be executed')
        raise exception.DatabaseMigrationError(reason=msg)
    if migrate:
        msg = _('migrate phase still has operations that need to be executed')
        raise exception.DatabaseMigrationError(reason=msg)

    context = _create_migration_context(as_sql=dryrun)
    ddlop = alembic.operations.Operations(context)
    for op in contract:
        op.execute(ddlop)

    repository = _find_migrate_repo(database)
    _set_db_sync_lock(repository, locked=False)
    _set_db_sync_version(repository, repository.latest)


def _process_null_records(table, col_name, check_fkeys, delete=False):
    """Queries the database and optionally deletes the NULL records.

    :param table: sqlalchemy.Table object.
    :param col_name: The name of the column to check in the table.
    :param check_fkeys: If True, check the table for foreign keys back to the
        instances table and if not found, return.
    :param delete: If true, run a delete operation on the table, else just
        query for number of records that match the NULL column.
    :returns: The number of records processed for the table and column.
    """
    records = 0
    if col_name in table.columns:
        # NOTE(mriedem): filter out tables that don't have a foreign key back
        # to the instances table since they could have stale data even if
        # instances.uuid wasn't NULL.
        if check_fkeys:
            fkey_found = False
            fkeys = table.c[col_name].foreign_keys or []
            for fkey in fkeys:
                if fkey.column.table.name == 'instances':
                    fkey_found = True

            if not fkey_found:
                return 0

        if delete:
            records = table.delete().where(
                table.c[col_name] == null()
            ).execute().rowcount
        else:
            records = len(list(
                table.select().where(table.c[col_name] == null()).execute()
            ))
    return records


def db_null_instance_uuid_scan(delete=False):
    """Scans the database for NULL instance_uuid records.

    :param delete: If true, delete NULL instance_uuid records found, else
                   just query to see if they exist for reporting.
    :returns: dict of table name to number of hits for NULL instance_uuid rows.
    """
    engine = get_engine()
    meta = sqlalchemy.MetaData(bind=engine)
    # NOTE(mriedem): We're going to load up all of the tables so we can find
    # any with an instance_uuid column since those may be foreign keys back
    # to the instances table and we want to cleanup those records first. We
    # have to do this explicitly because the foreign keys in nova aren't
    # defined with cascading deletes.
    meta.reflect(engine)
    # Keep track of all of the tables that had hits in the query.
    processed = {}
    for table in reversed(meta.sorted_tables):
        # Ignore the fixed_ips table by design.
        if table.name not in ('fixed_ips', 'shadow_fixed_ips'):
            processed[table.name] = _process_null_records(
                table, 'instance_uuid', check_fkeys=True, delete=delete)

    # Now process the *instances tables.
    for table_name in ('instances', 'shadow_instances'):
        table = db_utils.get_table(engine, table_name)
        processed[table.name] = _process_null_records(
            table, 'uuid', check_fkeys=False, delete=delete)

    return processed


def db_version_control(version=None, database='main'):
    repository = _find_migrate_repo(database)
    versioning_api.version_control(get_engine(database), repository, version)
    return version


def _find_migrate_repo(database='main'):
    """Get the path for the migrate repository."""
    global _REPOSITORY
    rel_path = 'migrate_repo'
    if database == 'api':
        rel_path = os.path.join('api_migrations', 'migrate_repo')
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        rel_path)
    assert os.path.exists(path)
    if _REPOSITORY.get(database) is None:
        _REPOSITORY[database] = Repository(path)
    return _REPOSITORY[database]
