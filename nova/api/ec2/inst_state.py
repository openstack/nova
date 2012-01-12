# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Isaku Yamahata <yamahata at valinux co jp>
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

PENDING_CODE = 0
RUNNING_CODE = 16
SHUTTING_DOWN_CODE = 32
TERMINATED_CODE = 48
STOPPING_CODE = 64
STOPPED_CODE = 80

PENDING = 'pending'
RUNNING = 'running'
SHUTTING_DOWN = 'shutting-down'
TERMINATED = 'terminated'
STOPPING = 'stopping'
STOPPED = 'stopped'

# non-ec2 value
SHUTOFF = 'shutoff'
MIGRATE = 'migrate'
RESIZE = 'resize'
PAUSE = 'pause'
SUSPEND = 'suspend'
RESCUE = 'rescue'

# EC2 API instance status code
_NAME_TO_CODE = {
    PENDING: PENDING_CODE,
    RUNNING: RUNNING_CODE,
    SHUTTING_DOWN: SHUTTING_DOWN_CODE,
    TERMINATED: TERMINATED_CODE,
    STOPPING: STOPPING_CODE,
    STOPPED: STOPPED_CODE,

    # approximation
    SHUTOFF: TERMINATED_CODE,
    MIGRATE: RUNNING_CODE,
    RESIZE: RUNNING_CODE,
    PAUSE: STOPPED_CODE,
    SUSPEND: STOPPED_CODE,
    RESCUE: RUNNING_CODE,
}


def name_to_code(name):
    return _NAME_TO_CODE.get(name, PENDING_CODE)
