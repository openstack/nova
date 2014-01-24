# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright 2014 Hewlett-Packard Development Company, L.P.
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

import errno
import os
import shutil

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.disk import api as disk_api
from nova.virt.libvirt import utils as libvirt_utils

LOG = logging.getLogger(__name__)


def cache_image(context, target, image_id, user_id, project_id, clean=False):
    if clean and os.path.exists(target):
        os.unlink(target)
    if not os.path.exists(target):
        libvirt_utils.fetch_image(context, target, image_id,
                                  user_id, project_id)


def inject_into_image(image, key, net, metadata, admin_password,
        files, partition, use_cow=False):
    try:
        disk_api.inject_data(image, key, net, metadata, admin_password,
                files, partition, use_cow)
    except Exception as e:
        LOG.warn(_("Failed to inject data into image %(image)s. "
                   "Error: %(e)s"), {'image': image, 'e': e})


def unlink_without_raise(path):
    try:
        os.unlink(path)
    except OSError as e:
        if e.errno == errno.ENOENT:
            return
        else:
            LOG.warn(_("Failed to unlink %(path)s, error: %(e)s"),
                     {'path': path, 'e': e})


def rmtree_without_raise(path):
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
    except OSError as e:
        LOG.warn(_("Failed to remove dir %(path)s, error: %(e)s"),
                 {'path': path, 'e': e})


def write_to_file(path, contents):
    with open(path, 'w') as f:
        f.write(contents)


def create_link_without_raise(source, link):
    try:
        os.symlink(source, link)
    except OSError as e:
        if e.errno == errno.EEXIST:
            return
        else:
            LOG.warn(_("Failed to create symlink from %(source)s to %(link)s"
                       ", error: %(e)s"),
                     {'source': source, 'link': link, 'e': e})


def random_alnum(count):
    import random
    import string
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(count))


def map_network_interfaces(network_info, use_ipv6=False):
    # TODO(deva): fix assumption that device names begin with "eth"
    #             and fix assumption about ordering
    if not isinstance(network_info, list):
        network_info = [network_info]

    interfaces = []
    for id, vif in enumerate(network_info):
        address_v6 = gateway_v6 = netmask_v6 = None
        address_v4 = gateway_v4 = netmask_v4 = dns_v4 = None

        if use_ipv6:
            subnets_v6 = [s for s in vif['network']['subnets']
                if s['version'] == 6]
            if len(subnets_v6):
                address_v6 = subnets_v6[0]['ips'][0]['address']
                netmask_v6 = subnets_v6[0].as_netaddr()._prefixlen
                gateway_v6 = subnets_v6[0]['gateway']['address']

        subnets_v4 = [s for s in vif['network']['subnets']
                if s['version'] == 4]
        if len(subnets_v4):
            address_v4 = subnets_v4[0]['ips'][0]['address']
            netmask_v4 = subnets_v4[0].as_netaddr().netmask
            gateway_v4 = subnets_v4[0]['gateway']['address']
            dns_v4 = ' '.join([x['address'] for x in subnets_v4[0]['dns']])

        interface = {
                'name': 'eth%d' % id,
                'address': address_v4,
                'gateway': gateway_v4,
                'netmask': netmask_v4,
                'dns': dns_v4,
                'address_v6': address_v6,
                'gateway_v6': gateway_v6,
                'netmask_v6': netmask_v6,
            }
        interfaces.append(interface)
    return interfaces
