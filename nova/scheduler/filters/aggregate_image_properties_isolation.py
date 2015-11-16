# Copyright (c) 2013 Cloudwatt
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

from oslo_log import log as logging
import six

import nova.conf
from nova.scheduler import filters
from nova.scheduler.filters import utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class AggregateImagePropertiesIsolation(filters.BaseHostFilter):
    """AggregateImagePropertiesIsolation works with image properties."""

    # Aggregate data and instance type does not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, spec_obj):
        """Checks a host in an aggregate that metadata key/value match
        with image properties.
        """
        cfg_namespace = CONF.aggregate_image_properties_isolation_namespace
        cfg_separator = CONF.aggregate_image_properties_isolation_separator

        image_props = spec_obj.image.properties if spec_obj.image else {}
        metadata = utils.aggregate_metadata_get_by_host(host_state)

        for key, options in six.iteritems(metadata):
            if (cfg_namespace and
                    not key.startswith(cfg_namespace + cfg_separator)):
                continue
            prop = image_props.get(key)
            # NOTE(sbauza): Aggregate metadata is only strings, we need to
            # stringify the property to match with the option
            # TODO(sbauza): Fix that very ugly pattern matching
            if prop and str(prop) not in options:
                LOG.debug("%(host_state)s fails image aggregate properties "
                            "requirements. Property %(prop)s does not "
                            "match %(options)s.",
                          {'host_state': host_state,
                           'prop': prop,
                           'options': options})
                return False
        return True
