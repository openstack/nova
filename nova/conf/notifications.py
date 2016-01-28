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

notify_on_state_change = cfg.StrOpt('notify_on_state_change',
        help='If set, send compute.instance.update notifications on instance '
             'state changes.  Valid values are None for no notifications, '
             '"vm_state" for notifications on VM state changes, or '
             '"vm_and_task_state" for notifications on VM and task state '
             'changes.')

notify_api_faults = cfg.BoolOpt('notify_api_faults', default=False,
        help='If set, send api.fault notifications on caught exceptions '
             'in the API service.')

default_notification_level = cfg.StrOpt('default_notification_level',
        default='INFO',
        choices=('DEBUG', 'INFO', 'WARN', 'ERROR', 'CRITICAL'),
        help='Default notification level for outgoing notifications')

default_publisher_id = cfg.StrOpt('default_publisher_id',
        help='Default publisher_id for outgoing notifications')

ALL_OPTS = [notify_on_state_change, notify_api_faults,
            default_notification_level,
            default_publisher_id]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {'DEFAULT': ALL_OPTS}
