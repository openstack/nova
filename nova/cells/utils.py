# Copyright (c) 2012 Rackspace Hosting
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

"""
Cells Utility Methods
"""
import random

from nova import db

# Separator used between cell names for the 'full cell name' and routing
# path
PATH_CELL_SEP = '!'
# Separator used between cell name and item
_CELL_ITEM_SEP = '@'


def get_instances_to_sync(context, updated_since=None, project_id=None,
        deleted=True, shuffle=False, uuids_only=False):
    """Return a generator that will return a list of active and
    deleted instances to sync with parent cells.  The list may
    optionally be shuffled for periodic updates so that multiple
    cells services aren't self-healing the same instances in nearly
    lockstep.
    """
    filters = {}
    if updated_since is not None:
        filters['changes-since'] = updated_since
    if project_id is not None:
        filters['project_id'] = project_id
    if not deleted:
        filters['deleted'] = False
    # Active instances first.
    instances = db.instance_get_all_by_filters(
            context, filters, 'deleted', 'asc')
    if shuffle:
        random.shuffle(instances)
    for instance in instances:
        if uuids_only:
            yield instance['uuid']
        else:
            yield instance


def cell_with_item(cell_name, item):
    """Turn cell_name and item into <cell_name>@<item>."""
    if cell_name is None:
        return item
    return cell_name + _CELL_ITEM_SEP + str(item)


def split_cell_and_item(cell_and_item):
    """Split a combined cell@item and return them."""
    result = cell_and_item.rsplit(_CELL_ITEM_SEP, 1)
    if len(result) == 1:
        return (None, cell_and_item)
    else:
        return result


def _add_cell_to_service(service, cell_name):
    service['id'] = cell_with_item(cell_name, service['id'])
    service['host'] = cell_with_item(cell_name, service['host'])


def add_cell_to_compute_node(compute_node, cell_name):
    """Fix compute_node attributes that should be unique.  Allows
    API cell to query the 'id' by cell@id.
    """
    compute_node['id'] = cell_with_item(cell_name, compute_node['id'])
    # Might have a 'service' backref.  But if is_primitive() was used
    # on this and it recursed too deep, 'service' may be "?".
    service = compute_node.get('service')
    if isinstance(service, dict):
        _add_cell_to_service(service, cell_name)


def add_cell_to_service(service, cell_name):
    """Fix service attributes that should be unique.  Allows
    API cell to query the 'id' or 'host' by cell@id/host.
    """
    _add_cell_to_service(service, cell_name)
    compute_node = service.get('compute_node')
    if compute_node:
        add_cell_to_compute_node(compute_node[0], cell_name)


def add_cell_to_task_log(task_log, cell_name):
    """Fix task_log attributes that should be unique.  In particular,
    the 'id' and 'host' fields should be prepended with cell name.
    """
    task_log['id'] = cell_with_item(cell_name, task_log['id'])
    task_log['host'] = cell_with_item(cell_name, task_log['host'])
