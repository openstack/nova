# Copyright (c) 2012-2013 Rackspace Hosting
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

"""
Target cell filter.

A scheduler hint of 'target_cell' with a value of a full cell name may be
specified to route a build to a particular cell.  No error handling is
done as there's no way to know whether the full path is a valid.
"""

from oslo_log import log as logging

from nova.cells import filters

LOG = logging.getLogger(__name__)


class TargetCellFilter(filters.BaseCellFilter):
    """Target cell filter.  Works by specifying a scheduler hint of
    'target_cell'. The value should be the full cell path.
    """

    def filter_all(self, cells, filter_properties):
        """Override filter_all() which operates on the full list
        of cells...
        """
        scheduler_hints = filter_properties.get('scheduler_hints')
        if not scheduler_hints:
            return cells

        # This filter only makes sense at the top level, as a full
        # cell name is specified.  So we pop 'target_cell' out of the
        # hints dict.
        cell_name = scheduler_hints.pop('target_cell', None)
        if not cell_name:
            return cells

        # This authorization is after popping off target_cell, so
        # that in case this fails, 'target_cell' is not left in the
        # dict when child cells go to schedule.
        if not self.authorized(filter_properties['context']):
            # No filtering, if not authorized.
            return cells

        LOG.info("Forcing direct route to %(cell_name)s because "
                 "of 'target_cell' scheduler hint",
                 {'cell_name': cell_name})

        scheduler = filter_properties['scheduler']
        if cell_name == filter_properties['routing_path']:
            return [scheduler.state_manager.get_my_state()]
        ctxt = filter_properties['context']

        scheduler.msg_runner.build_instances(ctxt, cell_name,
                filter_properties['host_sched_kwargs'])

        # Returning None means to skip further scheduling, because we
        # handled it.
