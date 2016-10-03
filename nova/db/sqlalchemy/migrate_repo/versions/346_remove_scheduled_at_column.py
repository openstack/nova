# Copyright 2016 Intel Corporation
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    column_name = 'scheduled_at'
    # Remove scheduled_at column from instances table
    instances = Table('instances', meta, autoload=True)
    shadow_instances = Table('shadow_instances', meta, autoload=True)

    if hasattr(instances.c, column_name):
        instances.drop_column(instances.c[column_name])

    if hasattr(shadow_instances.c, column_name):
        shadow_instances.drop_column(shadow_instances.c[column_name])
