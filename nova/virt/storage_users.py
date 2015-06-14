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


import os
import time

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova.i18n import _LW
from nova import utils

LOG = logging.getLogger(__name__)


CONF = cfg.CONF
TWENTY_FOUR_HOURS = 3600 * 24


# NOTE(morganfainberg): Due to circular import dependencies, the use of the
# CONF.instances_path needs to be wrapped so that it can be resolved at the
# appropriate time. Because compute.manager imports this file, we end up in
# a rather ugly dependency loop without moving this into a wrapped function.
# This issue mostly stems from the use of a decorator for the lock
# synchronize and the implications of how decorators wrap the wrapped function
# or method.  If this needs to be used outside of compute.manager, it should
# be refactored to eliminate this circular dependency loop.
# config option import is avoided here since it is
# explicitly imported from compute.manager and may cause issues with
# defining options after config has been processed with the
# wrapped-function style used here.

def register_storage_use(storage_path, hostname):
    """Identify the id of this instance storage."""

    LOCK_PATH = os.path.join(CONF.instances_path, 'locks')

    @utils.synchronized('storage-registry-lock', external=True,
                        lock_path=LOCK_PATH)
    def do_register_storage_use(storage_path, hostname):
        # NOTE(mikal): this is required to determine if the instance storage is
        # shared, which is something that the image cache manager needs to
        # know. I can imagine other uses as well though.

        d = {}
        id_path = os.path.join(storage_path, 'compute_nodes')
        if os.path.exists(id_path):
            with open(id_path) as f:
                try:
                    d = jsonutils.loads(f.read())
                except ValueError:
                    LOG.warning(_LW("Cannot decode JSON from %(id_path)s"),
                                {"id_path": id_path})

        d[hostname] = time.time()

        with open(id_path, 'w') as f:
            f.write(jsonutils.dumps(d))

    return do_register_storage_use(storage_path, hostname)


def get_storage_users(storage_path):
    """Get a list of all the users of this storage path."""

    # See comments above method register_storage_use

    LOCK_PATH = os.path.join(CONF.instances_path, 'locks')

    @utils.synchronized('storage-registry-lock', external=True,
                        lock_path=LOCK_PATH)
    def do_get_storage_users(storage_path):
        d = {}
        id_path = os.path.join(storage_path, 'compute_nodes')
        if os.path.exists(id_path):
            with open(id_path) as f:
                try:
                    d = jsonutils.loads(f.read())
                except ValueError:
                    LOG.warning(_LW("Cannot decode JSON from %(id_path)s"),
                                {"id_path": id_path})

        recent_users = []
        for node in d:
            if time.time() - d[node] < TWENTY_FOUR_HOURS:
                recent_users.append(node)

        return recent_users

    return do_get_storage_users(storage_path)
