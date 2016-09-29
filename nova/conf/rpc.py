# needs:fix_opt_description
# needs:check_deprecation_status
# needs:check_opt_group_and_type
# needs:fix_opt_description_indentation
# needs:fix_opt_registration_consistency


# Copyright 2016 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

notification_format = cfg.StrOpt(
    'notification_format',
    choices=['unversioned', 'versioned', 'both'],
    default='both',
    help="""Specifies which notification format shall be used by nova.

The default value is fine for most deployments and rarely needs to be changed.
This value can be set to 'versioned' once the infrastructure moves closer to
consuming the newer format of notifications. After this occurs, this option
will be removed (possibly in the "P" release).

Possible values:
* unversioned: Only the legacy unversioned notifications are emitted.
* versioned: Only the new versioned notifications are emitted.
* both: Both the legacy unversioned and the new versioned notifications are
  emitted. (Default)

The list of versioned notifications is visible in
http://docs.openstack.org/developer/nova/notifications.html

Related options:

* None""")

ALL_OPTS = [notification_format]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
