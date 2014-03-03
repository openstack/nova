#    Copyright 2014 Red Hat, Inc
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

"""Describes and verifies the watchdog device actions."""


# the values which may be passed to libvirt
RAW_WATCHDOG_ACTIONS = ['poweroff', 'reset', 'pause', 'none']


def is_valid_watchdog_action(val):
    """Check if the given value is a valid watchdog device parameter."""
    return val in RAW_WATCHDOG_ACTIONS
