# Copyright 2013 IBM Corp.
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


def upgrade(migration_engine):
    # Soft-delete all compute node stats whose corresponding compute node has
    # been deleted. Using "straight SQL" here as this will be a lot faster than
    # issuing individual updates for each (deleted) compute node.
    conn = migration_engine.connect()
    result = conn.execute(
        'update compute_node_stats set deleted = id, '
        'deleted_at = current_timestamp where compute_node_id in '
        '(select id from compute_nodes where deleted <> 0)')
    result.close()
    conn.close()


def downgrade(migration_engine):
    # This migration fixes compute nodes' stats. No need to go back and reverse
    # this change.
    pass
