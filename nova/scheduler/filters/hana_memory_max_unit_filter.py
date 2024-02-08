# Copyright (c) 2024 SAP SE
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

import nova.conf
from nova.scheduler import filters
from nova.scheduler import utils
from nova.utils import BIGVM_EXCLUSIVE_TRAIT

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class HANAMemoryMaxUnitFilter(filters.BaseHostFilter):
    """Memory max unit filter that runs only on HANA/BigVM flavors

    This filter is used to filter out those hosts which don't have
    enough memory reported by memory_mb_max_unit to fit the flavor.
    """

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        trait = f"trait:{BIGVM_EXCLUSIVE_TRAIT}"
        extra_specs = spec_obj.flavor.extra_specs
        if extra_specs.get(trait) != "required":
            return True

        memory_mb_max_unit = utils.get_memory_mb_max_unit(host_state)

        if memory_mb_max_unit is None:
            return True

        if memory_mb_max_unit >= spec_obj.memory_mb:
            return True

        LOG.info("%(host_state)s with memory_mb_max_unit = "
                 "%(memory_mb_max_unit)s doesn't have a node with enough "
                 "free RAM to fit a VM with memory_mb = %(memory_mb)s",
                 {"host_state": host_state,
                  "memory_mb_max_unit": memory_mb_max_unit,
                  "memory_mb": spec_obj.memory_mb})
        return False
