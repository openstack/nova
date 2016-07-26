# needs:check_deprecation_status
# needs:check_opt_group_and_type
# needs:fix_opt_description_indentation
# needs:fix_opt_registration_consistency


# Copyright 2015 OpenStack Foundation
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

from oslo_config import cfg

enable_guestfs_debug_opts = cfg.BoolOpt('debug',
                                        default=False,
                                        help="""
Enable the debug mode of "libguestfs".

If this node uses "libguestfs" (for example to inject data or passwords),
this option can be used to turn its debug mode on.

Possible values:
* True: turn debug on. This integrates libguestfs's logs into the log
  of OpenStack.
* False: turn debug off
""")

ALL_OPTS = [enable_guestfs_debug_opts]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group="guestfs")


def list_opts():
    return {"guestfs": ALL_OPTS}
