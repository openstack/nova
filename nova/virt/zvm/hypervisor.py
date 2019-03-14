# Copyright 2017,2018 IBM Corp.
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
import pwd

from oslo_log import log as logging

from nova.compute import power_state as compute_power_state
from nova import conf
from nova import exception
from nova.virt.zvm import utils as zvmutils


LOG = logging.getLogger(__name__)
CONF = conf.CONF


class Hypervisor(object):
    """z/VM implementation of Hypervisor."""

    def __init__(self, zcc_url, ca_file=None):
        super(Hypervisor, self).__init__()

        self._reqh = zvmutils.ConnectorClient(zcc_url,
                                              ca_file=ca_file)
        host_info = self._get_host_info()

        # Very very unlikely the hostname will be changed, so when create
        # hypervisor object, store the information in the cache and after
        # that we can use it directly without query again from connectorclient
        self._hypervisor_hostname = host_info['hypervisor_hostname']

        self._rhost = ''.join([pwd.getpwuid(os.geteuid()).pw_name, '@',
                               CONF.my_ip])

    def _get_host_info(self):
        host_stats = {}
        try:
            host_stats = self._reqh.call('host_get_info')
        except exception.ZVMConnectorError as e:
            LOG.warning("Failed to get host stats: %s", e)
        return host_stats

    def get_available_resource(self):
        return self._get_host_info()

    def get_available_nodes(self, refresh=False):
        # It's not expected that the hostname change, no need to take
        # 'refresh' into account.
        return [self._hypervisor_hostname]

    def list_names(self):
        """list names of the servers in the hypervisor"""
        return self._reqh.call('guest_list')

    def get_host_uptime(self):
        host_info = self._get_host_info()

        return host_info['ipl_time']

    def guest_exists(self, instance):
        return instance.name.upper() in self.list_names()

    def guest_get_power_state(self, name):
        power_state = compute_power_state.NOSTATE
        try:
            power_state = self._reqh.call('guest_get_power_state', name)
        except exception.ZVMConnectorError as err:
            if err.overallRC == 404:
                # instance does not exist
                LOG.warning("Failed to get power state due to nonexistent "
                            "instance: %s", name)
                raise exception.InstanceNotFound(instance_id=name)
            else:
                raise

        return power_state

    def guest_create(self, name, vcpus, memory_mb, disk_list):
        self._reqh.call('guest_create', name, vcpus, memory_mb,
                        disk_list=disk_list)

    def guest_deploy(self, name, image_name, transportfiles):
        self._reqh.call('guest_deploy', name, image_name,
                        transportfiles=transportfiles, remotehost=self._rhost)

    def guest_delete(self, name):
        self._reqh.call('guest_delete', name)

    def guest_start(self, name):
        self._reqh.call('guest_start', name)

    def guest_create_network_interface(self, name, distro, nets):
        self._reqh.call('guest_create_network_interface',
                        name, distro, nets)

    def guest_config_minidisks(self, name, disk_list):
        self._reqh.call('guest_config_minidisks', name, disk_list)

    def guest_capture(self, name, image_id):
        self._reqh.call('guest_capture', name, image_id)

    def guest_softstop(self, name, timeout=0, retry_interval=0):
        self._reqh.call('guest_softstop', name, timeout=timeout,
                        poll_interval=retry_interval)

    def guest_pause(self, name):
        self._reqh.call('guest_pause', name)

    def guest_unpause(self, name):
        self._reqh.call('guest_unpause', name)

    def guest_reboot(self, name):
        self._reqh.call('guest_reboot', name)

    def guest_reset(self, name):
        self._reqh.call('guest_reset', name)

    def guest_get_console_output(self, name):
        """get console out put of the given instance

        :returns: The output of the console of the instace, in string format.
        """
        return self._reqh.call('guest_get_console_output', name)

    def image_query(self, imagename):
        """Check whether image is there or not

        :returns: Query the image and returns a dict of the image info
                  if the image exists or return {}
        """
        return self._reqh.call('image_query', imagename=imagename)

    def image_get_root_disk_size(self, imagename):
        """Get the root disk size of image

        :returns: return the size (in string) about the root disk of image
        """
        return self._reqh.call('image_get_root_disk_size', imagename)

    def image_import(self, image_href, image_url, image_meta):
        self._reqh.call('image_import', image_href, image_url,
                        image_meta, remote_host=self._rhost)

    def image_export(self, image_id, dest_path):
        """export image to a given place

        :returns: a dict which represent the exported image information.
        """
        resp = self._reqh.call('image_export', image_id,
                               dest_path, remote_host=self._rhost)
        return resp

    def image_delete(self, image_id):
        self._reqh.call('image_delete', image_id)
