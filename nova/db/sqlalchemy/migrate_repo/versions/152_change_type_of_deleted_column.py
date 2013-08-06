from nova.db.sqlalchemy import utils
from sqlalchemy import CheckConstraint
from sqlalchemy.engine import reflection
from sqlalchemy.ext.compiler import compiles
from sqlalchemy import MetaData, Table, Column, Index
from sqlalchemy import select
from sqlalchemy.sql.expression import UpdateBase
from sqlalchemy import Integer, Boolean
from sqlalchemy.types import NullType, BigInteger


all_tables = ['services', 'compute_nodes', 'compute_node_stats',
              'certificates', 'instances', 'instance_info_caches',
              'instance_types', 'volumes', 'quotas', 'quota_classes',
              'quota_usages', 'reservations', 'snapshots',
              'block_device_mapping', 'iscsi_targets',
              'security_group_instance_association', 'security_groups',
              'security_group_rules', 'provider_fw_rules', 'key_pairs',
              'migrations', 'networks', 'virtual_interfaces', 'fixed_ips',
              'floating_ips', 'console_pools', 'consoles',
              'instance_metadata', 'instance_system_metadata',
              'instance_type_projects', 'instance_type_extra_specs',
              'aggregate_hosts', 'aggregate_metadata', 'aggregates',
              'agent_builds', 's3_images',
              'instance_faults',
              'bw_usage_cache', 'volume_id_mappings', 'snapshot_id_mappings',
              'instance_id_mappings', 'volume_usage_cache', 'task_log',
              'instance_actions', 'instance_actions_events']
# note(boris-42): We can't do migration for the dns_domains table because it
#                 doesn't have `id` column.

# NOTE(jhesketh): The following indexes are lost with this upgrade. We need to
#                 ensure they are added back in when downgrade() occurs.
lost_indexes_data = {
    # table_name: ((index_name_1, (*old_columns), (*new_columns)), ...)
    "certificates": (
        ("certificates_project_id_deleted_idx",
         ("project_id",), ("project_id", "deleted")),
        ("certificates_user_id_deleted_idx",
         ("user_id",), ("user_id", "deleted")),
    ),
    "instances": (
        ("instances_host_deleted_idx", ("host",), ("host", "deleted")),
        ("instances_uuid_deleted_idx", ("uuid",), ("uuid", "deleted")),
        ("instances_host_node_deleted_idx",
         ("host", "node"), ("host", "node", "deleted")),
    ),
    "iscsi_targets": (
        ("iscsi_targets_host_volume_id_deleted_idx",
         ("host", "volume_id"), ("host", "volume_id", "deleted")),
    ),
    "networks": (
        ("networks_bridge_deleted_idx", ("bridge",), ("bridge", "deleted")),
        ("networks_project_id_deleted_idx",
         ("project_id",), ("project_id", "deleted")),
        ("networks_uuid_project_id_deleted_idx",
         ("uuid", "project_id"), ("uuid", "project_id", "deleted")),
        ("networks_vlan_deleted_idx", ("vlan",), ("vlan", "deleted")),
    ),
    "fixed_ips": (
        ("fixed_ips_network_id_host_deleted_idx",
         ("network_id", "host"), ("network_id", "host", "deleted")),
        ("fixed_ips_address_reserved_network_id_deleted_idx",
         ("address", "reserved", "network_id"),
         ("address", "reserved", "network_id", "deleted")),
        ("fixed_ips_deleted_allocated_idx",
         ("address", "allocated"),
         ('address', 'deleted', 'allocated')),
    ),
    "floating_ips": (
        ("floating_ips_pool_deleted_fixed_ip_id_project_id_idx",
         ("pool", "fixed_ip_id", "project_id"),
         ("pool", "deleted", "fixed_ip_id", "project_id")),
    ),
    "instance_faults": (
        ("instance_faults_instance_uuid_deleted_created_at_idx",
         ("instance_uuid", "created_at"),
         ("instance_uuid", "deleted", "created_at")),
    ),
    "migrations": (
        ("migrations_instance_uuid_and_status_idx",
         ("instance_uuid", "status"),
         ("deleted", "instance_uuid", "status")),
    ),
}


class InsertFromSelect(UpdateBase):
    def __init__(self, table, select):
        self.table = table
        self.select = select


@compiles(InsertFromSelect)
def visit_insert_from_select(element, compiler, **kw):
    return "INSERT INTO %s %s" % (
        compiler.process(element.table, asfrom=True),
        compiler.process(element.select))


def get_default_deleted_value(table):
    if isinstance(table.c.id.type, Integer):
        return 0
    # NOTE(boris-42): There is only one other type that is used as id (String)
    return ""


def upgrade_enterprise_dbs(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    for table_name in all_tables:
        table = Table(table_name, meta, autoload=True)

        new_deleted = Column('new_deleted', table.c.id.type,
                             default=get_default_deleted_value(table))
        new_deleted.create(table, populate_default=True)

        table.update().\
                where(table.c.deleted == True).\
                values(new_deleted=table.c.id).\
                execute()
        table.c.deleted.drop()
        table.c.new_deleted.alter(name="deleted")


def upgrade(migrate_engine):
    if migrate_engine.name != "sqlite":
        return upgrade_enterprise_dbs(migrate_engine)

    # NOTE(boris-42): sqlaclhemy-migrate can't drop column with check
    #                 constraints in sqlite DB and our `deleted` column has
    #                 2 check constraints. So there is only one way to remove
    #                 these constraints:
    #                 1) Create new table with the same columns, constraints
    #                 and indexes. (except deleted column).
    #                 2) Copy all data from old to new table.
    #                 3) Drop old table.
    #                 4) Rename new table to old table name.
    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData()
    meta.bind = migrate_engine

    for table_name in all_tables:
        table = Table(table_name, meta, autoload=True)
        default_deleted_value = get_default_deleted_value(table)

        columns = []
        for column in table.columns:
            column_copy = None
            if column.name != "deleted":
                # NOTE(boris-42): BigInteger is not supported by sqlite, so
                #                 after copy it will have NullType, other
                #                 types that are used in Nova are supported by
                #                 sqlite.
                if isinstance(column.type, NullType):
                    column_copy = Column(column.name, BigInteger(), default=0)
                else:
                    column_copy = column.copy()
            else:
                column_copy = Column('deleted', table.c.id.type,
                                     default=default_deleted_value)
            columns.append(column_copy)

        def is_deleted_column_constraint(constraint):
            # NOTE(boris-42): There is no other way to check is CheckConstraint
            #                 associated with deleted column.
            if not isinstance(constraint, CheckConstraint):
                return False
            sqltext = str(constraint.sqltext)
            return (sqltext.endswith("deleted in (0, 1)") or
                    sqltext.endswith("deleted IN (:deleted_1, :deleted_2)"))

        constraints = []
        for constraint in table.constraints:
            if not is_deleted_column_constraint(constraint):
                constraints.append(constraint.copy())

        new_table = Table(table_name + "__tmp__", meta,
                          *(columns + constraints))
        new_table.create()

        indexes = []
        for index in insp.get_indexes(table_name):
            column_names = [new_table.c[c] for c in index['column_names']]
            indexes.append(Index(index["name"],
                                 *column_names,
                                 unique=index["unique"]))

        ins = InsertFromSelect(new_table, table.select())
        migrate_engine.execute(ins)

        table.drop()
        [index.create(migrate_engine) for index in indexes]

        new_table.rename(table_name)
        new_table.update().\
            where(new_table.c.deleted == True).\
            values(deleted=new_table.c.id).\
            execute()

        # NOTE(boris-42): Fix value of deleted column: False -> "" or 0.
        new_table.update().\
            where(new_table.c.deleted == False).\
            values(deleted=default_deleted_value).\
            execute()


def downgrade_enterprise_dbs(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    for table_name in all_tables:
        table = Table(table_name, meta, autoload=True)

        old_deleted = Column('old_deleted', Boolean, default=False)
        old_deleted.create(table, populate_default=False)

        table.update().\
                where(table.c.deleted == table.c.id).\
                values(old_deleted=True).\
                execute()

        table.c.deleted.drop()
        table.c.old_deleted.alter(name="deleted")

    # NOTE(jhesketh): Unfortunately indexes were lost with this upgrade
    # so we need to recreate them so the downgrade is consistent with
    # the previous state.

    if migrate_engine.name == "mysql":
        # NOTE(jhesketh): MySQL kept the second index due to migration 144
        # where it was added with a truncated key to be compatible with
        # mysql.
        sql = ("drop index migrations_by_host_nodes_and_status_idx ON "
               "migrations")
        migrate_engine.execute(sql)

        sql = ("create index migrations_by_host_nodes_and_status_idx ON "
               "migrations (deleted, source_compute(100), "
               "dest_compute(100), source_node(100), dest_node(100), "
               "status)")

        migrate_engine.execute(sql)
    else:
        lost_indexes_data['migrations'] = ((
            'migrations_instance_uuid_and_status_idx',
            ('instance_uuid', 'status'),
            ('deleted', 'instance_uuid', 'status'),
        ), (
            'migrations_by_host_nodes_and_status_idx',
            ('source_compute', 'dest_compute', 'source_node',
             'dest_node', 'status'),
            ('deleted', 'source_compute', 'dest_compute', 'source_node',
             'dest_node', 'status'),
        ))

    utils.modify_indexes(migrate_engine, lost_indexes_data)


def downgrade(migrate_engine):
    if migrate_engine.name != "sqlite":
        return downgrade_enterprise_dbs(migrate_engine)

    insp = reflection.Inspector.from_engine(migrate_engine)
    meta = MetaData()
    meta.bind = migrate_engine

    for table_name in all_tables:
        table = Table(table_name, meta, autoload=True)

        columns = []
        for column in table.columns:
            column_copy = None
            if column.name != "deleted":
                if isinstance(column.type, NullType):
                    column_copy = Column(column.name, BigInteger(), default=0)
                else:
                    column_copy = column.copy()
            else:
                column_copy = Column('deleted', Boolean, default=0)
            columns.append(column_copy)

        constraints = [constraint.copy() for constraint in table.constraints]

        new_table = Table(table_name + "__tmp__", meta,
                          *(columns + constraints))
        new_table.create()

        indexes = []
        for index in insp.get_indexes(table_name):
            column_names = [new_table.c[c] for c in index['column_names']]
            indexes.append(Index(index["name"],
                                 *column_names,
                                 unique=index["unique"]))

        c_select = []
        for c in table.c:
            if c.name != "deleted":
                c_select.append(c)
            else:
                c_select.append(table.c.deleted == table.c.id)

        ins = InsertFromSelect(new_table, select(c_select))
        migrate_engine.execute(ins)

        table.drop()
        [index.create(migrate_engine) for index in indexes]

        new_table.rename(table_name)
        new_table.update().\
            where(new_table.c.deleted == new_table.c.id).\
            values(deleted=True).\
            execute()
