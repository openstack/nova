# Copyright 2012 Hewlett-Packard Development Company, L.P.

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
#
# Virtual power driver commands


class vbox(object):
    """set commands for basic Virtual Box control."""

    def __init__(self):
        self.base_cmd = '/usr/bin/VBoxManage'
        self.start_cmd = 'startvm {_NodeName_}'
        self.stop_cmd = 'controlvm {_NodeName_} poweroff'
        self.reboot_cmd = 'controlvm {_NodeName_} reset'
        self.list_cmd = "list vms|awk -F'\"' '{print $2}'"
        self.list_running_cmd = 'list runningvms'
        self.get_node_macs = ("showvminfo --machinereadable {_NodeName_} | "
                "grep "
                '"macaddress" | awk -F '
                "'"
                '"'
                "' '{print $2}'")


class virsh(object):
    """set commands for basic Virsh control."""

    def __init__(self):
        self.base_cmd = '/usr/bin/virsh'
        self.start_cmd = 'start {_NodeName_}'
        self.stop_cmd = 'destroy {_NodeName_}'
        self.reboot_cmd = 'reset {_NodeName_}'
        self.list_cmd = "list --all | tail -n +2 | awk -F\" \" '{print $2}'"
        self.list_running_cmd = \
            "list --all|grep running|awk -v qc='\"' -F\" \" '{print qc$2qc}'"
        self.get_node_macs = ("dumpxml {_NodeName_} | grep "
            '"mac address" | awk -F'
            '"'
            "'"
            '" '
            "'{print $2}' | tr -d ':'")
