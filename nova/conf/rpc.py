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

Possible values:
* unversioned: Only the legacy unversioned notifications are emitted.
* versioned: Only the new versioned notifications are emitted.
* both: Both the legacy unversioned and the new versioned notifications are
  emitted. (Default)

Currently there is no feature parity between unversioned and versioned
notifications. If the deployment needs the full range of legacy notifications
then the recommended setting is 'both' or 'unversioned'. Nova does not allow
adding new legacy notifications so new notification will be emitted as
versioned notifications. If the deployment needs the new notifications then
either 'both' or 'versioned' value is required. The list of versioned
notifications is visible in
http://docs.openstack.org/developer/nova/notifications.html
Nova is planning to deprecate this parameter as soon as feature parity is
achieved.

This is an advanced option, deployers rarely needs to change the default value.

Services which consume this:

* nova-api
* nova-conductor
* nova-compute
* nova-scheduler

Related options:

* None""")

ALL_OPTS = [notification_format]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
