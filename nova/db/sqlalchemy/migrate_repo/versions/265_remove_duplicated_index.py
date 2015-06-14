# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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


from sqlalchemy import MetaData, Table


INDEXES = [
    # subset of instances_host_deleted_cleaned_idx
    ('instances', 'instances_host_deleted_idx'),
    # subset of iscsi_targets_host_volume_id_deleted_idx
    ('iscsi_targets', 'iscsi_targets_host_idx'),
]


def upgrade(migrate_engine):
    """Remove index that are subsets of other indexes."""

    meta = MetaData(bind=migrate_engine)

    for table_name, index_name in INDEXES:
        table = Table(table_name, meta, autoload=True)
        for index in table.indexes:
            if index.name == index_name:
                index.drop()
