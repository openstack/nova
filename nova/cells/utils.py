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
