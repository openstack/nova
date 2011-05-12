# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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

"""The various power states that a VM can be in."""

#NOTE(justinsb): These are the virDomainState values from libvirt
NOSTATE = 0x00
RUNNING = 0x01
BLOCKED = 0x02
PAUSED = 0x03
SHUTDOWN = 0x04
SHUTOFF = 0x05
CRASHED = 0x06
SUSPENDED = 0x07
FAILED = 0x08
BUILDING = 0x09

# TODO(justinsb): Power state really needs to be a proper class,
# so that we're not locked into the libvirt status codes and can put mapping
# logic here rather than spread throughout the code
_STATE_MAP = {
    NOSTATE: 'pending',
    RUNNING: 'running',
    BLOCKED: 'blocked',
    PAUSED: 'paused',
    SHUTDOWN: 'shutdown',
    SHUTOFF: 'shutdown',
    CRASHED: 'crashed',
    SUSPENDED: 'suspended',
    FAILED: 'failed to spawn',
    BUILDING: 'building',
}


def name(code):
    return _STATE_MAP[code]


def valid_states():
    return _STATE_MAP.keys()
