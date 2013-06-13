#!/usr/bin/env python

# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
One-time script to populate VDI.other_config.

We use metadata stored in VDI.other_config to associate a VDI with a given
instance so that we may safely cleanup orphaned VDIs.

We had a bug in the code that meant that the vast majority of VDIs created
would not have the other_config populated.

After deploying the fixed code, this script is intended to be run against all
compute-workers in a cluster so that existing VDIs can have their other_configs
populated.

Run on compute-worker (not Dom0):

    python ./tools/xenserver/populate_other_config.py [--dry-run|--verbose]
"""
import os
import sys

possible_topdir = os.getcwd()
if os.path.exists(os.path.join(possible_topdir, "nova", "__init__.py")):
        sys.path.insert(0, possible_topdir)

from nova import config
from nova.openstack.common import uuidutils
from nova.virt import virtapi
from nova.virt.xenapi import driver as xenapi_driver
from nova.virt.xenapi import vm_utils
from oslo.config import cfg

cli_opts = [
    cfg.BoolOpt('dry-run',
               default=False,
               help='Whether to actually update other_config.'),
]

CONF = cfg.CONF
CONF.register_cli_opts(cli_opts)


def main():
    config.parse_args(sys.argv)

    xenapi = xenapi_driver.XenAPIDriver(virtapi.VirtAPI())
    session = xenapi._session

    vdi_refs = session.call_xenapi('VDI.get_all')
    for vdi_ref in vdi_refs:
        vdi_rec = session.call_xenapi('VDI.get_record', vdi_ref)

        other_config = vdi_rec['other_config']

        # Already set...
        if 'nova_instance_uuid' in other_config:
            continue

        name_label = vdi_rec['name_label']

        # We only want name-labels of form instance-<UUID>-[optional-suffix]
        if not name_label.startswith('instance-'):
            continue

        # Parse out UUID
        instance_uuid = name_label.replace('instance-', '')[:36]
        if not uuidutils.is_uuid_like(instance_uuid):
            print "error: name label '%s' wasn't UUID-like" % name_label
            continue

        vdi_type = vdi_rec['name_description']

        # We don't need a full instance record, just the UUID
        instance = {'uuid': instance_uuid}

        if not CONF.dry_run:
            vm_utils._set_vdi_info(session, vdi_ref, vdi_type, name_label,
                                   vdi_type, instance)

        if CONF.verbose:
            print "Setting other_config for instance_uuid=%s vdi_uuid=%s" % (
                    instance_uuid, vdi_rec['uuid'])

        if CONF.dry_run:
            print "Dry run completed"


if __name__ == "__main__":
    main()
