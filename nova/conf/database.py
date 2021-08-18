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

import copy

from oslo_config import cfg
from oslo_db import options as oslo_db_opts

main_db_group = cfg.OptGroup(
    name='database',
    title='Main Database Options',
    help="""
The *Nova Database* is the primary database which is used for information
local to a *cell*.

This group should **not** be configured for the ``nova-compute`` service.
""")

api_db_group = cfg.OptGroup(
    name='api_database',
    title='API Database Options',
    help="""
The *Nova API Database* is a separate database which is used for information
which is used across *cells*. This database is mandatory since the Mitaka
release (13.0.0).

This group should **not** be configured for the ``nova-compute`` service.
""")

# NOTE(stephenfin): We cannot simply use 'oslo_db_options.database_opts'
# directly. If we reuse a db config option for two different groups
# ("api_database" and "database") and deprecate or rename a config option in
# one of these groups, "oslo.config" cannot correctly determine which one to
# update. That's why we copy these.
main_db_opts = copy.deepcopy(oslo_db_opts.database_opts)
api_db_opts = copy.deepcopy(oslo_db_opts.database_opts)

# We don't support the experimental use of database reconnect on connection
# lost, so remove the config option that would suggest we do
main_db_opts = [opt for opt in main_db_opts if opt.name != 'use_db_reconnect']
api_db_opts = [opt for opt in main_db_opts if opt.name != 'use_db_reconnect']


def register_opts(conf):
    conf.register_opts(main_db_opts, group=main_db_group)
    conf.register_opts(api_db_opts, group=api_db_group)


def list_opts():
    return {
        main_db_group: main_db_opts,
        api_db_group: api_db_opts,
    }
