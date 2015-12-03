# Copyright 2013 Cloudbase Solutions Srl
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

from os_win import utilsfactory
from oslo_log import log as logging

from nova.console import type as ctype
from nova.virt.hyperv import hostops

LOG = logging.getLogger(__name__)


class RDPConsoleOps(object):
    def __init__(self):
        self._hostops = hostops.HostOps()
        self._vmutils = utilsfactory.get_vmutils()
        self._rdpconsoleutils = utilsfactory.get_rdpconsoleutils()

    def get_rdp_console(self, instance):
        LOG.debug("get_rdp_console called", instance=instance)
        host = self._hostops.get_host_ip_addr()
        port = self._rdpconsoleutils.get_rdp_console_port()
        vm_id = self._vmutils.get_vm_id(instance.name)

        LOG.debug("RDP console: %(host)s:%(port)s, %(vm_id)s",
                  {"host": host, "port": port, "vm_id": vm_id})

        return ctype.ConsoleRDP(
            host=host, port=port, internal_access_path=vm_id)
