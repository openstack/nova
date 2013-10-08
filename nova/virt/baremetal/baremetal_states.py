# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2010 OpenStack Foundation
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

"""
Possible baremetal node states for instances.

Compute instance baremetal states represent the state of an instance as it
pertains to a user or administrator. When combined with task states
(task_states.py), a better picture can be formed regarding the instance's
health.

"""

NULL = None
INIT = 'initializing'
ACTIVE = 'active'
BUILDING = 'building'
DEPLOYING = 'deploying'
DEPLOYFAIL = 'deploy failed'
DEPLOYDONE = 'deploy complete'
DELETED = 'deleted'
ERROR = 'error'
PREPARED = 'prepared'
