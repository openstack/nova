#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

"""
destroy_cached_images.py

This script is used to clean up Glance images that are cached in the SR. By
default, this script will only cleanup unused cached images.

Options:

    --dry_run - Don't actually destroy the VDIs
    --all_cached - Destroy all cached images instead of just unused cached
                   images.
    --keep_days - N - Only remove those cached images which were created
                      more than N days ago.
"""
import eventlet
eventlet.monkey_patch()

import os
import sys

from os_xenapi.client import session
from oslo_config import cfg

# If ../nova/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...
POSSIBLE_TOPDIR = os.path.normpath(os.path.join(os.path.abspath(sys.argv[0]),
                                   os.pardir,
                                   os.pardir,
                                   os.pardir))
if os.path.exists(os.path.join(POSSIBLE_TOPDIR, 'nova', '__init__.py')):
    sys.path.insert(0, POSSIBLE_TOPDIR)

import nova.conf
from nova import config
from nova.virt.xenapi import vm_utils

destroy_opts = [
    cfg.BoolOpt('all_cached',
                default=False,
                help='Destroy all cached images instead of just unused cached'
                     ' images.'),
    cfg.BoolOpt('dry_run',
                default=False,
                help='Don\'t actually delete the VDIs.'),
    cfg.IntOpt('keep_days',
               default=0,
               help='Destroy cached images which were'
                    ' created over keep_days.')
]

CONF = nova.conf.CONF
CONF.register_cli_opts(destroy_opts)

def main():
    config.parse_args(sys.argv)

    _session = session.XenAPISession(CONF.xenserver.connection_url,
                                     CONF.xenserver.connection_username,
                                     CONF.xenserver.connection_password)

    sr_ref = vm_utils.safe_find_sr(_session)
    destroyed = vm_utils.destroy_cached_images(
        _session, sr_ref, all_cached=CONF.all_cached,
        dry_run=CONF.dry_run, keep_days=CONF.keep_days)

    if '--verbose' in sys.argv:
        print('\n'.join(destroyed))

    print("Destroyed %d cached VDIs" % len(destroyed))


if __name__ == "__main__":
    main()
