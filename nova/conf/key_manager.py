# Copyright 2016 OpenStack Foundation
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

from castellan import options as castellan_opts
from oslo_config import cfg

key_manager_group = cfg.OptGroup(
    'key_manager',
    title='Key manager options')

key_manager_opts = [
    # TODO(raj_singh): Deprecate or move this option to The Castellan library
    cfg.StrOpt(
        'fixed_key',
        deprecated_group='keymgr',
        secret=True,
        help="""
Fixed key returned by key manager, specified in hex.

Possible values:

* Empty string or a key in hex value
"""),
]


def register_opts(conf):
    castellan_opts.set_defaults(conf)
    conf.register_group(key_manager_group)
    conf.register_opts(key_manager_opts, group=key_manager_group)


def list_opts():
    # Castellan library also has a group name key_manager. So if
    # we append list returned from Castellan to this list, oslo will remove
    # one group as duplicate and only one group (either from this file or
    # Castellan library) will show up. So fix is to merge options of same
    # group name from this file and Castellan library
    opts = {key_manager_group.name: key_manager_opts}
    for group, options in castellan_opts.list_opts():
        if group not in opts.keys():
            opts[group] = options
        else:
            opts[group] = opts[group] + options
    return opts
    # TODO(raj_singh): When the last option "fixed_key" is removed/moved from
    # this file, then comment in code below and delete the code block above.
    # Castellan already returned a list which can be returned
    # directly from list_opts()
    # return castellan_opts.list_opts()
