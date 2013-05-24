# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Mirantis, Inc.
# Copyright 2013 OpenStack Foundation
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
#
# @author: Boris Pavlovic, Mirantis Inc

from nova.db.sqlalchemy import utils


def upgrade(migrate_engine):
    utils.change_deleted_column_type_to_id_type(migrate_engine, 'shadow_cells')


def downgrade(migrate_engine):
    utils.change_deleted_column_type_to_boolean(migrate_engine, 'shadow_cells')
