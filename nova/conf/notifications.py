# Copyright (c) 2016 Intel, Inc.
# Copyright (c) 2013 OpenStack Foundation
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

ALL_OPTS = [
    cfg.StrOpt(
        'notify_on_state_change',
        choices=(None, 'vm_state', 'vm_and_task_state'),
        help="""
If set, send compute.instance.update notifications on instance state
changes.

Please refer to https://wiki.openstack.org/wiki/SystemUsageData for
additional information on notifications.

Possible values:

* None - no notifications
* "vm_state" - notifications on VM state changes
* "vm_and_task_state" - notifications on VM and task state changes
"""),

    cfg.BoolOpt(
        'notify_api_faults',
        default=False,
        help="""
If enabled, send api.fault notifications on caught exceptions in the
API service.
"""),

    cfg.StrOpt(
        'default_notification_level',
        default='INFO',
        choices=('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'),
        help="Default notification level for outgoing notifications."),

    cfg.StrOpt(
        'default_publisher_id',
        default='$my_ip',
        help="""
Default publisher_id for outgoing notifications. If you consider routing
notifications using different publisher, change this value accordingly.

Possible values:

* Defaults to the IPv4 address of this host, but it can be any valid
  oslo.messaging publisher_id

Related options:

*  my_ip - IP address of this host
"""),
    cfg.StrOpt(
        'notification_format',
        choices=['unversioned', 'versioned', 'both'],
        default='both',
        help="""
Specifies which notification format shall be used by nova.

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
"""),
]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


# TODO(johngarbutt): we should move this to a notification group.
def list_opts():
    return {'DEFAULT': ALL_OPTS}
