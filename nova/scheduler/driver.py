# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Scheduler base class that all Schedulers should inherit from
"""

import datetime

from nova import db
from nova import exception
from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_integer('daemon_down_time',
                     60,
                     'seconds without heartbeat that determines a '
                         'compute node to be down')

class NoValidHost(exception.Error):
    """There is no valid host for the command"""
    pass

class Scheduler(object):
    """
    The base class that all Scheduler clases should inherit from
    """

    @staticmethod
    def daemon_is_up(daemon):
        """
        Given a daemon, return whether the deamon is considered 'up' by
        if it's sent a heartbeat recently
        """
        elapsed = datetime.datetime.now() - daemon['updated_at']
        return elapsed < datetime.timedelta(seconds=FLAGS.daemon_down_time)

    def hosts_up(self, context, topic):
        """
        Return the list of hosts that have a running daemon for topic
        """

        daemons = db.daemon_get_all_by_topic(context, topic)
        return [daemon.host
                for daemon in daemons
                if self.daemon_is_up(daemon)]
