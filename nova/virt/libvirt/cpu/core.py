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

import os
import typing as ty

from oslo_log import log as logging

from nova import exception
from nova import filesystem
import nova.privsep
from nova.virt import hardware

LOG = logging.getLogger(__name__)

AVAILABLE_PATH = '/sys/devices/system/cpu/present'

CPU_PATH_TEMPLATE = '/sys/devices/system/cpu/cpu%(core)s'


def get_available_cores() -> ty.Set[int]:
    cores = filesystem.read_sys(AVAILABLE_PATH)
    return hardware.parse_cpu_spec(cores) if cores else set()


def exists(core: int) -> bool:
    return core in get_available_cores()


def gen_cpu_path(core: int) -> str:
    if not exists(core):
        LOG.warning('Unable to access CPU: %s', core)
        raise ValueError('CPU: %(core)s does not exist', core)
    return CPU_PATH_TEMPLATE % {'core': core}


def get_online(core: int) -> bool:
    try:
        online = filesystem.read_sys(
            os.path.join(gen_cpu_path(core), 'online')).strip()
    except exception.FileNotFound:
        # The online file may not exist if we haven't written it yet.
        # By default, this means that the CPU is online.
        online = '1'
    return online == '1'


@nova.privsep.sys_admin_pctxt.entrypoint
def set_online(core: int) -> bool:
    filesystem.write_sys(os.path.join(gen_cpu_path(core), 'online'), data='1')
    return get_online(core)


@nova.privsep.sys_admin_pctxt.entrypoint
def set_offline(core: int) -> bool:
    filesystem.write_sys(os.path.join(gen_cpu_path(core), 'online'), data='0')
    return not get_online(core)


def get_governor(core: int) -> str:
    return filesystem.read_sys(
        os.path.join(gen_cpu_path(core), 'cpufreq/scaling_governor')).strip()


@nova.privsep.sys_admin_pctxt.entrypoint
def set_governor(core: int, governor: str) -> str:
    filesystem.write_sys(
        os.path.join(gen_cpu_path(core), 'cpufreq/scaling_governor'),
        data=governor)
    return get_governor(core)
