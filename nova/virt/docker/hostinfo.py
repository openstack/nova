# Copyright (c) 2013 dotCloud, Inc.
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

import os


def statvfs():
    docker_path = '/var/lib/docker'
    if not os.path.exists(docker_path):
        docker_path = '/'
    return os.statvfs(docker_path)


def get_meminfo():
    with open('/proc/meminfo') as f:
        return f.readlines()


def get_disk_usage():
    # This is the location where Docker stores its containers. It's currently
    # hardcoded in Docker so it's not configurable yet.
    st = statvfs()
    return {
        'total': st.f_blocks * st.f_frsize,
        'available': st.f_bavail * st.f_frsize,
        'used': (st.f_blocks - st.f_bfree) * st.f_frsize
    }


def parse_meminfo():
    meminfo = {}
    for ln in get_meminfo():
        parts = ln.split(':')
        if len(parts) < 2:
            continue
        key = parts[0].lower()
        value = parts[1].strip()
        parts = value.split(' ')
        value = parts[0]
        if not value.isdigit():
            continue
        value = int(parts[0])
        if len(parts) > 1 and parts[1] == 'kB':
            value *= 1024
        meminfo[key] = value
    return meminfo


def get_memory_usage():
    meminfo = parse_meminfo()
    total = meminfo.get('memtotal', 0)
    free = meminfo.get('memfree', 0)
    free += meminfo.get('cached', 0)
    free += meminfo.get('buffers', 0)
    return {
        'total': total,
        'free': free,
        'used': total - free
    }


def get_mounts():
    with open('/proc/mounts') as f:
        return f.readlines()


def get_cgroup_devices_path():
    for ln in get_mounts():
        fields = ln.split(' ')
        if fields[2] == 'cgroup' and 'devices' in fields[3].split(','):
            return fields[1]
