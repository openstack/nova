# Copyright 2014 Rackspace Hosting
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


from oslo_log import log as logging
from sqlalchemy import MetaData, Table, Index

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Change instances (project_id) index to cover (project_id, deleted)."""

    meta = MetaData(bind=migrate_engine)

    # Indexes can't be changed, we need to create the new one and delete
    # the old one

    instances = Table('instances', meta, autoload=True)

    for index in instances.indexes:
        if [c.name for c in index.columns] == ['project_id', 'deleted']:
            LOG.info('Skipped adding instances_project_id_deleted_idx '
                     'because an equivalent index already exists.')
            break
    else:
        index = Index('instances_project_id_deleted_idx',
                      instances.c.project_id, instances.c.deleted)
        index.create()

    for index in instances.indexes:
        if [c.name for c in index.columns] == ['project_id']:
            index.drop()
