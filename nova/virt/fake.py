# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
A fake (in-memory) hypervisor+api. Allows nova testing w/o a hypervisor.
"""

import logging

from nova.compute import power_state


def get_connection(_):
    # The read_only parameter is ignored.
    return FakeConnection.instance()


class FakeConnection(object):
    def __init__(self):
        self.instances = {}

    @classmethod
    def instance(cls):
        if not hasattr(cls, '_instance'):
            cls._instance = cls()
        return cls._instance

    def list_instances(self):
        return self.instances.keys()

    def spawn(self, instance):
        fake_instance = FakeInstance()
        self.instances[instance.id] = fake_instance
        fake_instance._state = power_state.RUNNING

    def reboot(self, instance):
        pass
       
    def destroy(self, instance):
        del self.instances[instance.id]

    def get_info(self, instance_id):
        i = self.instances[instance_id]
        return {'state': i._state,
                'max_mem': 0,
                'mem': 0,
                'num_cpu': 2,
                'cpu_time': 0}

    def list_disks(self, instance_id):
        return ['A_DISK']

    def list_interfaces(self, instance_id):
        return ['A_VIF']

    def block_stats(self, instance_id, disk_id):
        return [0L, 0L, 0L, 0L, null]

    def interface_stats(self, instance_id, iface_id):
        return [0L, 0L, 0L, 0L, 0L, 0L, 0L, 0L]


class FakeInstance(object):
    def __init__(self):
        self._state = power_state.NOSTATE
