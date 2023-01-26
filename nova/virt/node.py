#    Copyright 2022 Red Hat, inc.
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

import logging
import os
import uuid

from oslo_utils import uuidutils

import nova.conf
from nova import exception

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
COMPUTE_ID_FILE = 'compute_id'
LOCAL_NODE_UUID = None


def write_local_node_uuid(node_uuid):
    # We only ever write an identity file in the CONF.state_path
    # location
    fn = os.path.join(CONF.state_path, COMPUTE_ID_FILE)

    # Try to create the identity file and write our uuid into it. Fail
    # if the file exists (since it shouldn't if we made it here).
    try:
        with open(fn, 'x') as f:
            f.write(node_uuid)
    except FileExistsError:
        # If the file exists, we must either fail or re-survey all the
        # potential files. If we just read and return it, it could be
        # inconsistent with files in the other locations.
        raise exception.InvalidNodeConfiguration(
            reason='Identity file %s appeared unexpectedly' % fn)
    except Exception as e:
        raise exception.InvalidNodeConfiguration(
            reason='Unable to write uuid to %s: %s' % (fn, e))

    LOG.info('Wrote node identity %s to %s', node_uuid, fn)


def read_local_node_uuid():
    locations = ([os.path.dirname(f) for f in CONF.config_file] +
                 [CONF.state_path])

    uuids = []
    found = []
    for location in locations:
        fn = os.path.join(location, COMPUTE_ID_FILE)
        try:
            # UUIDs should be 36 characters in canonical format. Read
            # a little more to be graceful about whitespace in/around
            # the actual value we want to read. However, it must parse
            # to a legit UUID once we strip the whitespace.
            with open(fn) as f:
                content = f.read(40)
            node_uuid = str(uuid.UUID(content.strip()))
        except FileNotFoundError:
            continue
        except ValueError:
            raise exception.InvalidNodeConfiguration(
                reason='Unable to parse UUID from %s' % fn)
        uuids.append(node_uuid)
        found.append(fn)

    if uuids:
        # Any identities we found must be consistent, or we fail
        first = uuids[0]
        for i, (node_uuid, fn) in enumerate(zip(uuids, found)):
            if node_uuid != first:
                raise exception.InvalidNodeConfiguration(
                    reason='UUID %s in %s does not match %s' % (
                        node_uuid, fn, uuids[i - 1]))
        LOG.info('Determined node identity %s from %s', first, found[0])
        return first
    else:
        return None


def get_local_node_uuid():
    """Read or create local node uuid file.

    :returns: UUID string read from file, or generated
    """
    global LOCAL_NODE_UUID

    if LOCAL_NODE_UUID is not None:
        return LOCAL_NODE_UUID

    node_uuid = read_local_node_uuid()
    if not node_uuid:
        node_uuid = uuidutils.generate_uuid()
        LOG.info('Generated node identity %s', node_uuid)
        write_local_node_uuid(node_uuid)

    LOCAL_NODE_UUID = node_uuid
    return node_uuid
