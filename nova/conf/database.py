# Copyright 2015 OpenStack Foundation
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

from nova.conf import paths

from oslo_config import cfg
from oslo_db import options as oslo_db_options

_DEFAULT_SQL_CONNECTION = 'sqlite:///' + paths.state_path_def('nova.sqlite')


# NOTE(sdague): we know of at least 1 instance of out of tree usage
# for this config in RAX. They used this because of performance issues
# with some queries. We think the right path forward is fixing the
# SQLA queries to be more performant for everyone.
db_driver_opt = cfg.StrOpt(
        'db_driver',
        default='nova.db',
        help='DEPRECATED: The driver to use for database access',
        deprecated_for_removal=True)


# NOTE(markus_z): We cannot simply do:
# conf.register_opts(oslo_db_options.database_opts, 'api_database')
# If we reuse a db config option for two different groups ("api_database"
# and "database") and deprecate or rename a config option in one of these
# groups, "oslo.config" cannot correctly determine which one to update.
# That's why we copied & pasted these config options for the "api_database"
# group here. See commit ba407e3 ("Add support for multiple database engines")
# for more details.
api_db_opts = [
    cfg.StrOpt('connection',
               help='The SQLAlchemy connection string to use to connect to '
                    'the Nova API database.',
               secret=True),
    cfg.BoolOpt('sqlite_synchronous',
                default=True,
                help='If True, SQLite uses synchronous mode.'),
    cfg.StrOpt('slave_connection',
               secret=True,
               help='The SQLAlchemy connection string to use to connect to the'
                    ' slave database.'),
    cfg.StrOpt('mysql_sql_mode',
               default='TRADITIONAL',
               help='The SQL mode to be used for MySQL sessions. '
                    'This option, including the default, overrides any '
                    'server-set SQL mode. To use whatever SQL mode '
                    'is set by the server configuration, '
                    'set this to no value. Example: mysql_sql_mode='),
    cfg.IntOpt('idle_timeout',
               default=3600,
               help='Timeout before idle SQL connections are reaped.'),
    cfg.IntOpt('max_pool_size',
               help='Maximum number of SQL connections to keep open in a '
                    'pool.'),
    cfg.IntOpt('max_retries',
               default=10,
               help='Maximum number of database connection retries '
                    'during startup. Set to -1 to specify an infinite '
                    'retry count.'),
    cfg.IntOpt('retry_interval',
               default=10,
               help='Interval between retries of opening a SQL connection.'),
    cfg.IntOpt('max_overflow',
               help='If set, use this value for max_overflow with '
                    'SQLAlchemy.'),
    cfg.IntOpt('connection_debug',
               default=0,
               help='Verbosity of SQL debugging information: 0=None, '
                    '100=Everything.'),
    cfg.BoolOpt('connection_trace',
                default=False,
                help='Add Python stack traces to SQL as comment strings.'),
    cfg.IntOpt('pool_timeout',
               help='If set, use this value for pool_timeout with '
                    'SQLAlchemy.'),
]


def register_opts(conf):
    oslo_db_options.set_defaults(conf, connection=_DEFAULT_SQL_CONNECTION,
                         sqlite_db='nova.sqlite')
    conf.register_opt(db_driver_opt)
    conf.register_opts(api_db_opts, group='api_database')


def list_opts():
    # NOTE(markus_z): 2016-04-04: If we list the oslo_db_options here, they
    #                 get emitted twice(!) in the "sample.conf" file. First
    #                 under the namespace "nova.conf" and second under the
    #                 namespace "oslo.db". This is due to the setting in file
    #                 "etc/nova/nova-config-generator.conf". As I think it
    #                 is useful to have the "oslo.db" namespace information
    #                 in the "sample.conf" file, I omit the listing of the
    #                 "oslo_db_options" here.
    return {'DEFAULT': [db_driver_opt],
            'api_database': api_db_opts,
            }
