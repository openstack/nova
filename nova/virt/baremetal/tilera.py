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

"""
Tilera back-end for bare-metal compute node provisioning

The details of this implementation are specific to ISI's testbed. This code
is provided here as an example of how to implement a backend.
"""

import base64
import os
import subprocess
import time

from nova.compute import power_state
from nova.openstack.common import cfg
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils

FLAGS = flags.FLAGS

global_opts = [
    cfg.StrOpt('tile_monitor',
               default='/usr/local/TileraMDE/bin/tile-monitor',
               help='Tilera command line program for Bare-metal driver')
    ]

FLAGS.add_options(global_opts)

LOG = logging.getLogger('nova.virt.tilera')


def get_baremetal_nodes():
    return BareMetalNodes()


class BareMetalNodes(object):
    """
    This manages node information and implements singleton.

    BareMetalNodes class handles machine architectures of interest to
    technical computing users have either poor or non-existent support
    for virtualization.
    """

    _instance = None
    _is_init = False

    def __new__(cls, *args, **kwargs):
        """
        Returns the BareMetalNodes singleton.
        """
        if not cls._instance or ('new' in kwargs and kwargs['new']):
            cls._instance = super(BareMetalNodes, cls).__new__(cls)
        return cls._instance

    def __init__(self, file_name="/tftpboot/tilera_boards"):
        """
        Only call __init__ the first time object is instantiated.

        From the bare-metal node list file: /tftpboot/tilera_boards,
        reads each item of each node such as node ID, IP address,
        MAC address, vcpus, memory, hdd, hypervisor type/version, and cpu
        and appends each node information into nodes list.
        """
        if self._is_init:
            return
        self._is_init = True

        self.nodes = []
        self.BOARD_ID = 0
        self.IP_ADDR = 1
        self.MAC_ADDR = 2
        self.VCPUS = 3
        self.MEMORY_MB = 4
        self.LOCAL_GB = 5
        self.MEMORY_MB_USED = 6
        self.LOCAL_GB_USED = 7
        self.HYPERVISOR_TYPE = 8
        self.HYPERVISOR_VER = 9
        self.CPU_INFO = 10

        fp = open(file_name, "r")
        for item in fp:
            l = item.split()
            if l[0] == '#':
                continue
            l_d = {'node_id': int(l[self.BOARD_ID]),
                    'ip_addr': l[self.IP_ADDR],
                    'mac_addr': l[self.MAC_ADDR],
                    'status': power_state.NOSTATE,
                    'vcpus': int(l[self.VCPUS]),
                    'memory_mb': int(l[self.MEMORY_MB]),
                    'local_gb': int(l[self.LOCAL_GB]),
                    'memory_mb_used': int(l[self.MEMORY_MB_USED]),
                    'local_gb_used': int(l[self.LOCAL_GB_USED]),
                    'hypervisor_type': l[self.HYPERVISOR_TYPE],
                    'hypervisor_version': int(l[self.HYPERVISOR_VER]),
                    'cpu_info': l[self.CPU_INFO]}
            self.nodes.append(l_d)
        fp.close()

    def get_hw_info(self, field):
        """
        Returns hardware information of bare-metal node by the given field.

        Given field can be vcpus, memory_mb, local_gb, memory_mb_used,
        local_gb_used, hypervisor_type, hypervisor_version, and cpu_info.
        """
        for node in self.nodes:
            if node['node_id'] == 9:
                if field == 'vcpus':
                    return node['vcpus']
                elif field == 'memory_mb':
                    return node['memory_mb']
                elif field == 'local_gb':
                    return node['local_gb']
                elif field == 'memory_mb_used':
                    return node['memory_mb_used']
                elif field == 'local_gb_used':
                    return node['local_gb_used']
                elif field == 'hypervisor_type':
                    return node['hypervisor_type']
                elif field == 'hypervisor_version':
                    return node['hypervisor_version']
                elif field == 'cpu_info':
                    return node['cpu_info']

    def set_status(self, node_id, status):
        """
        Sets status of the given node by the given status.

        Returns 1 if the node is in the nodes list.
        """
        for node in self.nodes:
            if node['node_id'] == node_id:
                node['status'] = status
                return True
        return False

    def get_status(self):
        """
        Gets status of the given node.
        """
        pass

    def get_idle_node(self):
        """
        Gets an idle node, sets the status as 1 (RUNNING) and Returns node ID.
        """
        for item in self.nodes:
            if item['status'] == 0:
                item['status'] = 1      # make status RUNNING
                return item['node_id']
        raise exception.NotFound("No free nodes available")

    def get_ip_by_id(self, id):
        """
        Returns default IP address of the given node.
        """
        for item in self.nodes:
            if item['node_id'] == id:
                return item['ip_addr']

    def free_node(self, node_id):
        """
        Sets/frees status of the given node as 0 (IDLE).
        """
        LOG.debug(_("free_node...."))
        for item in self.nodes:
            if item['node_id'] == str(node_id):
                item['status'] = 0  # make status IDLE

    def power_mgr(self, node_id, mode):
        """
        Changes power state of the given node.

        According to the mode (1-ON, 2-OFF, 3-REBOOT), power state can be
        changed. /tftpboot/pdu_mgr script handles power management of
        PDU (Power Distribution Unit).
        """
        if node_id < 5:
            pdu_num = 1
            pdu_outlet_num = node_id + 5
        else:
            pdu_num = 2
            pdu_outlet_num = node_id
        path1 = "10.0.100." + str(pdu_num)
        utils.execute('/tftpboot/pdu_mgr', path1, str(pdu_outlet_num), \
            str(mode), '>>', 'pdu_output')

    def deactivate_node(self, node_id):
        """
        Deactivates the given node by turnning it off.

        /tftpboot/fs_x directory is a NFS of node#x
        and /tftpboot/root_x file is an file system image of node#x.
        """
        node_ip = self.get_ip_by_id(node_id)
        LOG.debug(_("deactivate_node is called for \
               node_id = %(id)s node_ip = %(ip)s"),
               {'id': str(node_id), 'ip': node_ip})
        for item in self.nodes:
            if item['node_id'] == node_id:
                LOG.debug(_("status of node is set to 0"))
                item['status'] = 0
        self.power_mgr(node_id, 2)
        self.sleep_mgr(5)
        path = "/tftpboot/fs_" + str(node_id)
        pathx = "/tftpboot/root_" + str(node_id)
        utils.execute('sudo', '/usr/sbin/rpc.mountd')
        try:
            utils.execute('sudo', 'umount', '-f', pathx)
            utils.execute('sudo', 'rm', '-f', pathx)
        except:
            LOG.debug(_("rootfs is already removed"))

    def network_set(self, node_ip, mac_address, ip_address):
        """
        Sets network configuration based on the given ip and mac address.

        User can access the bare-metal node using ssh.
        """
        cmd = FLAGS.tile_monitor + \
            " --resume --net " + node_ip + " --run - " + \
            "ifconfig xgbe0 hw ether " + mac_address + \
            " - --wait --run - ifconfig xgbe0 " + ip_address + \
            " - --wait --quit"
        subprocess.Popen(cmd, shell=True)
        #utils.execute(cmd, shell=True)
        self.sleep_mgr(5)

    def iptables_set(self, node_ip, user_data):
        """
        Sets security setting (iptables:port) if needed.

        iptables -A INPUT -p tcp ! -s $IP --dport $PORT -j DROP
        /tftpboot/iptables_rule script sets iptables rule on the given node.
        """
        if user_data != '':
            open_ip = base64.b64decode(user_data)
            utils.execute('/tftpboot/iptables_rule', node_ip, open_ip)

    def check_activated(self, node_id, node_ip):
        """
        Checks whether the given node is activated or not.
        """
        LOG.debug(_("Before ping to the bare-metal node"))
        tile_output = "/tftpboot/tile_output_" + str(node_id)
        grep_cmd = "ping -c1 " + node_ip + " | grep Unreachable > " \
                   + tile_output
        subprocess.Popen(grep_cmd, shell=True)
        self.sleep_mgr(5)

        file = open(tile_output, "r")
        out_msg = file.readline().find("Unreachable")
        utils.execute('sudo', 'rm', tile_output)
        if out_msg == -1:
            cmd = "TILERA_BOARD_#" + str(node_id) + " " + node_ip \
                + " is ready"
            LOG.debug(_(cmd))
            return True
        else:
            cmd = "TILERA_BOARD_#" + str(node_id) + " " \
                + node_ip + " is not ready, out_msg=" + out_msg
            LOG.debug(_(cmd))
            self.power_mgr(node_id, 2)
            return False

    def vmlinux_set(self, node_id, mode):
        """
        Sets kernel into default path (/tftpboot) if needed.

        From basepath to /tftpboot, kernel is set based on the given mode
        such as 0-NoSet, 1-SetVmlinux, or 9-RemoveVmlinux.
        """
        cmd = "Noting to do for tilera nodes: vmlinux is in CF"
        LOG.debug(_(cmd))

    def sleep_mgr(self, time_in_seconds):
        """
        Sleeps until the node is activated.
        """
        time.sleep(time_in_seconds)

    def ssh_set(self, node_ip):
        """
        Sets and Runs sshd in the node.
        """
        cmd = FLAGS.tile_monitor + \
            " --resume --net " + node_ip + " --run - " + \
            "/usr/sbin/sshd - --wait --quit"
        subprocess.Popen(cmd, shell=True)
        self.sleep_mgr(5)

    def activate_node(self, node_id, node_ip, name, mac_address, \
                      ip_address, user_data):
        """
        Activates the given node using ID, IP, and MAC address.
        """
        LOG.debug(_("activate_node"))

        self.power_mgr(node_id, 2)
        self.power_mgr(node_id, 3)
        self.sleep_mgr(100)

        try:
            self.check_activated(node_id, node_ip)
            self.network_set(node_ip, mac_address, ip_address)
            self.ssh_set(node_ip)
            self.iptables_set(node_ip, user_data)
            return power_state.RUNNING
        except Exception as ex:
            self.deactivate_node(node_id)
            raise exception.Error(_("Node is unknown error state."))

    def get_console_output(self, console_log, node_id):
        """
        Gets console output of the given node.
        """
        node_ip = self.get_ip_by_id(node_id)
        log_path = "/tftpboot/log_" + str(node_id)
        kmsg_cmd = FLAGS.tile_monitor + \
                   " --resume --net " + node_ip + \
                   " -- dmesg > " + log_path
        subprocess.Popen(kmsg_cmd, shell=True)
        self.sleep_mgr(5)
        utils.execute('cp', log_path, console_log)

    def get_image(self, bp):
        """
        Gets the bare-metal file system image into the instance path.

        Noting to do for tilera nodes: actual image is used.
        """
        path_fs = "/tftpboot/tilera_fs"
        path_root = bp + "/root"
        utils.execute('cp', path_fs, path_root)

    def set_image(self, bpath, node_id):
        """
        Sets the PXE bare-metal file system from the instance path.

        This should be done after ssh key is injected.
        /tftpboot/fs_x directory is a NFS of node#x.
        /tftpboot/root_x file is an file system image of node#x.
        """
        path1 = bpath + "/root"
        pathx = "/tftpboot/root_" + str(node_id)
        path2 = "/tftpboot/fs_" + str(node_id)
        utils.execute('sudo', 'mv', path1, pathx)
        utils.execute('sudo', 'mount', '-o', 'loop', pathx, path2)
