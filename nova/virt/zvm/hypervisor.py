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

from oslo_log import log as logging

from nova import exception
from nova.virt.zvm import utils as zvmutils


LOG = logging.getLogger(__name__)


class Hypervisor(object):
    """z/VM implementation of Hypervisor."""

    def __init__(self, zcc_url, ca_file=None):
        super(Hypervisor, self).__init__()

        self._reqh = zvmutils.ConnectorClient(zcc_url,
                                              ca_file=ca_file)

        # Very very unlikely the hostname will be changed, so when create
        # hypervisor object, store the information in the cache and after
        # that we can use it directly without query again from connectorclient
        self._hypervisor_hostname = self._get_host_info().get(
            'hypervisor_hostname')

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
