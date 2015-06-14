# Copyright 2013 OpenStack Foundation
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

"""Possible actions on an instance.

Actions should probably match a user intention at the API level.  Because they
can be user visible that should help to avoid confusion.  For that reason they
tend to maintain the casing sent to the API.

Maintaining a list of actions here should protect against inconsistencies when
they are used.
"""

CREATE = 'create'
DELETE = 'delete'
EVACUATE = 'evacuate'
RESTORE = 'restore'
STOP = 'stop'
START = 'start'
REBOOT = 'reboot'
REBUILD = 'rebuild'
REVERT_RESIZE = 'revertResize'
CONFIRM_RESIZE = 'confirmResize'
RESIZE = 'resize'
MIGRATE = 'migrate'
PAUSE = 'pause'
UNPAUSE = 'unpause'
SUSPEND = 'suspend'
RESUME = 'resume'
RESCUE = 'rescue'
UNRESCUE = 'unrescue'
CHANGE_PASSWORD = 'changePassword'
SHELVE = 'shelve'
UNSHELVE = 'unshelve'
LIVE_MIGRATION = 'live-migration'
