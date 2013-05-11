# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Michael Still and Canonical Inc
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


import json
import os
import time

from nova import utils


TWENTY_FOUR_HOURS = 3600 * 24


@utils.synchronized('storage-registry-lock', external=True)
def register_storage_use(storage_path, hostname):
    """Idenfity the id of this instance storage."""

    # NOTE(mikal): this is required to determine if the instance storage is
    # shared, which is something that the image cache manager needs to
    # know. I can imagine other uses as well though.

    d = {}
    id_path = os.path.join(storage_path, 'compute_nodes')
    if os.path.exists(id_path):
        with open(id_path) as f:
            d = json.loads(f.read())

    d[hostname] = time.time()

    with open(id_path, 'w') as f:
        f.write(json.dumps(d))


@utils.synchronized('storage-registry-lock', external=True)
def get_storage_users(storage_path):
    """Get a list of all the users of this storage path."""

    d = {}
    id_path = os.path.join(storage_path, 'compute_nodes')
    if os.path.exists(id_path):
        with open(id_path) as f:
            d = json.loads(f.read())

    recent_users = []
    for node in d:
        if time.time() - d[node] < TWENTY_FOUR_HOURS:
            recent_users.append(node)

    return recent_users
