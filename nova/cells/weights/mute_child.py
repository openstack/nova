# Copyright (c) 2013 Rackspace Hosting
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
If a child cell hasn't sent capacity or capability updates in a while,
downgrade its likelihood of being chosen for scheduling requests.
"""

from oslo_config import cfg
from oslo_utils import timeutils

from nova.cells import weights
from nova.i18n import _LW
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

mute_weigher_opts = [
        cfg.FloatOpt('mute_weight_multiplier',
                default=-10.0,
                help='Multiplier used to weigh mute children. (The value '
                     'should be negative.)'),
        cfg.FloatOpt('mute_weight_value',
                default=1000.0,
                help='Weight value assigned to mute children. (The value '
                     'should be positive.)'),
]

CONF = cfg.CONF
CONF.import_opt('mute_child_interval', 'nova.cells.opts', group='cells')
CONF.register_opts(mute_weigher_opts, group='cells')


class MuteChildWeigher(weights.BaseCellWeigher):
    """If a child cell hasn't been heard from, greatly lower its selection
    weight.
    """

    def weight_multiplier(self):
        # negative multiplier => lower weight
        return CONF.cells.mute_weight_multiplier

    def _weigh_object(self, cell, weight_properties):
        """Check cell against the last_seen timestamp that indicates the time
        that the most recent capability or capacity update was received from
        the given cell.
        """

        last_seen = cell.last_seen
        secs = CONF.cells.mute_child_interval

        if timeutils.is_older_than(last_seen, secs):
            # yep, that's a mute child;  recommend highly that it be skipped!
            LOG.warning(_LW("%(cell)s has not been seen since %(last_seen)s "
                            "and is being treated as mute."),
                        {'cell': cell, 'last_seen': last_seen})
            return CONF.cells.mute_weight_value
        else:
            return 0
