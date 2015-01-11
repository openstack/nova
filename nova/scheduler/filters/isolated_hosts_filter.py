# Copyright (c) 2011-2012 OpenStack Foundation
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

from oslo_config import cfg

from nova.scheduler import filters

isolated_opts = [
    cfg.ListOpt('isolated_images',
                default=[],
                help='Images to run on isolated host'),
    cfg.ListOpt('isolated_hosts',
                default=[],
                help='Host reserved for specific images'),
    cfg.BoolOpt('restrict_isolated_hosts_to_isolated_images',
                default=True,
                help='Whether to force isolated hosts to run only isolated '
                     'images'),
]
CONF = cfg.CONF
CONF.register_opts(isolated_opts)


class IsolatedHostsFilter(filters.BaseHostFilter):
    """Keep specified images to selected hosts."""

    # The configuration values do not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, filter_properties):
        """Result Matrix with 'restrict_isolated_hosts_to_isolated_images' set
        to True::

        |                | isolated_image | non_isolated_image
        |   -------------+----------------+-------------------
        |   iso_host     |    True        |     False
        |   non_iso_host |    False       |      True

        Result Matrix with 'restrict_isolated_hosts_to_isolated_images' set
        to False::

        |                | isolated_image | non_isolated_image
        |   -------------+----------------+-------------------
        |   iso_host     |    True        |      True
        |   non_iso_host |    False       |      True

        """
        # If the configuration does not list any hosts, the filter will always
        # return True, assuming a configuration error, so letting all hosts
        # through.
        isolated_hosts = CONF.isolated_hosts
        isolated_images = CONF.isolated_images
        restrict_isolated_hosts_to_isolated_images = (CONF.
                                   restrict_isolated_hosts_to_isolated_images)
        if not isolated_images:
            # As there are no images to match, return True if the filter is
            # not restrictive otherwise return False if the host is in the
            # isolation list.
            return ((not restrict_isolated_hosts_to_isolated_images) or
                   (host_state.host not in isolated_hosts))

        spec = filter_properties.get('request_spec', {})
        props = spec.get('instance_properties', {})
        image_ref = props.get('image_ref')
        image_isolated = image_ref in isolated_images
        host_isolated = host_state.host in isolated_hosts

        if restrict_isolated_hosts_to_isolated_images:
            return (image_isolated == host_isolated)
        else:
            return (not image_isolated) or host_isolated
