# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 University of Southern California
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


def get_baremetal_nodes():
    return BareMetalNodes()


class BareMetalNodes(object):
    """
    This manages node information and implements singleton.

    BareMetalNodes class handles machine architectures of interest to
    technical computing users have either poor or non-existent support
    for virtualization.
    """

    def get_hw_info(self, field):
        """
        Returns hardware information of bare-metal node by the given field.

        Given field can be vcpus, memory_mb, local_gb, memory_mb_used,
        local_gb_used, hypervisor_type, hypervisor_version, and cpu_info.
        """
        return "fake"

    def set_status(self, node_id, status):
        """
        Sets status of the given node by the given status.

        Returns 1 if the node is in the nodes list.
        """
        return True

    def get_status(self):
        """
        Gets status of the given node.
        """
        pass

    def get_idle_node(self):
        """
        Gets an idle node, sets the status as 1 (RUNNING) and Returns node ID.
        """
        return False

    def get_ip_by_id(self, id):
        """
        Returns default IP address of the given node.
        """
        return "127.0.0.1"

    def free_node(self, node_id):
        """
        Sets/frees status of the given node as 0 (IDLE).
        """
        return False

    def power_mgr(self, node_id, mode):
        """
        Changes power state of the given node.

        According to the mode (1-ON, 2-OFF, 3-REBOOT), power state can be
        changed. /tftpboot/pdu_mgr script handles power management of
        PDU (Power Distribution Unit).
        """
        pass

    def deactivate_node(self, node_id):
        """
        Deactivates the given node by turnning it off.
        """
        pass

    def network_set(self, node_ip, mac_address, ip_address):
        """
        Sets network configuration based on the given ip and mac address.

        User can access the bare-metal node using ssh.
        """
        pass

    def iptables_set(self, node_ip, user_data):
        """
        Sets security setting (iptables:port) if needed.
        """
        pass

    def check_activated(self, node_id, node_ip):
        """
        Checks whether the given node is activated or not.
        """
        pass

    def vmlinux_set(self, node_id, mode):
        """
        Sets kernel into default path (/tftpboot) if needed.

        From basepath to /tftpboot, kernel is set based on the given mode
        such as 0-NoSet, 1-SetVmlinux, or 9-RemoveVmlinux.
        """
        pass

    def sleep_mgr(self, time):
        """
        Sleeps until the node is activated.
        """
        pass

    def ssh_set(self, node_ip):
        """
        Sets and Runs sshd in the node.
        """
        pass

    def activate_node(self, node_id, node_ip, name, mac_address, \
                      ip_address):
        """
        Activates the given node using ID, IP, and MAC address.
        """
        pass

    def get_console_output(self, console_log):
        """
        Gets console output of the given node.
        """
        pass

    def get_image(self, bp):
        """
        Gets the bare-metal file system image into the instance path.

        Noting to do for tilera nodes: actual image is used.
        """
        pass

    def set_image(self, bpath, node_id):
        """
        Sets the PXE bare-metal file system from the instance path.

        This should be done after ssh key is injected.
        """
        pass
