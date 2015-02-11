# Copyright (c) AT&T 2012-2013 Yun Mao <yunmao@gmail.com>
# Copyright 2012 IBM Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import eventlet
from oslo_config import cfg
from oslo_utils import importutils

from nova import exception
from nova.i18n import _LE, _LW
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.servicegroup.drivers import base

evzookeeper = importutils.try_import('evzookeeper')
membership = importutils.try_import('evzookeeper.membership')
zookeeper = importutils.try_import('zookeeper')

zk_driver_opts = [
    cfg.StrOpt('address',
               help='The ZooKeeper addresses for servicegroup service in the '
                    'format of host1:port,host2:port,host3:port'),
    cfg.IntOpt('recv_timeout',
               default=4000,
               help='The recv_timeout parameter for the zk session'),
    cfg.StrOpt('sg_prefix',
               default="/servicegroups",
               help='The prefix used in ZooKeeper to store ephemeral nodes'),
    cfg.IntOpt('sg_retry_interval',
               default=5,
               help='Number of seconds to wait until retrying to join the '
                    'session'),
    ]

CONF = cfg.CONF
CONF.register_opts(zk_driver_opts, group="zookeeper")

LOG = logging.getLogger(__name__)


class ZooKeeperDriver(base.Driver):
    """ZooKeeper driver for the service group API."""

    def __init__(self, *args, **kwargs):
        """Create the zk session object."""
        if not all([evzookeeper, membership, zookeeper]):
            raise ImportError('zookeeper module not found')
        self._memberships = {}
        self._monitors = {}
        super(ZooKeeperDriver, self).__init__()
        self._cached_session = None

    @property
    def _session(self):
        """Creates zookeeper session in lazy manner.

        Session is created in lazy manner to mitigate lock problem
        in zookeeper.

        Lock happens when many processes try to use the same zk handle.
        Lazy creation allows to deffer initialization of session until
        is really required by worker (child process).

        :returns: ZKSession -- new or created earlier
        """
        if self._cached_session is None:
            self._cached_session = self._init_session()
        return self._cached_session

    def _init_session(self):
        """Initializes new session.

        Optionally creates required servicegroup prefix.

        :returns ZKSession - newly created session
        """
        null = open(os.devnull, "w")
        session = evzookeeper.ZKSession(CONF.zookeeper.address,
                                              recv_timeout=
                                                CONF.zookeeper.recv_timeout,
                                              zklog_fd=null)
        # Make sure the prefix exists
        try:
            session.create(CONF.zookeeper.sg_prefix, "",
                                 acl=[evzookeeper.ZOO_OPEN_ACL_UNSAFE])
        except zookeeper.NodeExistsException:
            pass
        # Log a warning about quality for this driver.
        LOG.warning(_LW('The ZooKeeper service group driver in Nova is not '
                        'tested by the OpenStack project and thus its quality '
                        'can not be ensured. This may change in the future, '
                        'but current deployers should be aware that the use '
                        'of it in production right now may be risky.'))
        return session

    def join(self, member_id, group, service=None):
        """Join the given service with its group."""
        # process id
        process_id = str(os.getpid())
        LOG.debug('ZooKeeperDriver: join new member %(id)s(%(pid)s) to the '
                  '%(gr)s group, service=%(sr)s',
                  {'id': member_id, 'pid': process_id,
                   'gr': group, 'sr': service})
        member = self._memberships.get((group, member_id), None)
        if member is None:
            # the first time to join. Generate a new object
            path = "%s/%s/%s" % (CONF.zookeeper.sg_prefix, group, member_id)
            try:
                member = membership.Membership(self._session, path, process_id)
            except RuntimeError:
                LOG.exception(_LE("Unable to join. It is possible that either"
                                  " another node exists with the same name, or"
                                  " this node just restarted. We will try "
                                  "again in a short while to make sure."))
                eventlet.sleep(CONF.zookeeper.sg_retry_interval)
                member = membership.Membership(self._session, path, member_id)
            self._memberships[(group, member_id)] = member
        return FakeLoopingCall(self, member_id, group)

    def leave(self, member_id, group):
        """Remove the given member from the service group."""
        LOG.debug('ZooKeeperDriver.leave: %(member)s from group %(group)s',
                  {'member': member_id, 'group': group})
        try:
            key = (group, member_id)
            member = self._memberships[key]
            member.leave()
            del self._memberships[key]
        except KeyError:
            LOG.error(_LE('ZooKeeperDriver.leave: %(id)s has not joined '
                          'to the %(gr)s group'),
                      {'id': member_id, 'gr': group})

    def is_up(self, service_ref):
        group_id = service_ref['topic']
        member_id = service_ref['host']
        all_members = self.get_all(group_id)
        return member_id in all_members

    def get_all(self, group_id):
        """Return all members in a list, or a ServiceGroupUnavailable
        exception.
        """
        monitor = self._monitors.get(group_id, None)
        if monitor is None:
            path = "%s/%s" % (CONF.zookeeper.sg_prefix, group_id)

            null = open(os.devnull, "w")
            local_session = evzookeeper.ZKSession(CONF.zookeeper.address,
                                                  recv_timeout=
                                                  CONF.zookeeper.recv_timeout,
                                                  zklog_fd=null)

            monitor = membership.MembershipMonitor(local_session, path)
            self._monitors[group_id] = monitor
            # Note(maoy): When initialized for the first time, it takes a
            # while to retrieve all members from zookeeper. To prevent
            # None to be returned, we sleep 5 sec max to wait for data to
            # be ready.
            timeout = 5  # seconds
            interval = 0.1
            tries = int(timeout / interval)
            for _retry in range(tries):
                eventlet.sleep(interval)
                all_members = monitor.get_all()
                if all_members is not None:
                    # Stop the tries once the cache is populated
                    LOG.debug('got info about members in %r: %r',
                              path, ', '.join(all_members))
                    break
            else:
                # if all_members, weren't populated
                LOG.warning(_LW('Problem with acquiring the list of '
                                'children of %(path)r within a given '
                                'timeout=%(timeout)rs'),
                            path, timeout)
        else:
            all_members = monitor.get_all()

        if all_members is None:
            raise exception.ServiceGroupUnavailable(driver="ZooKeeperDriver")

        def have_processes(member):
            """Predicate that given member has processes (subnode exists)."""
            value, stat = monitor.get_member_details(member)
            # only check nodes that are created by Membership class
            if value == 'ZKMembers':
                num_children = stat['numChildren']
                return num_children > 0
            else:
                # unknown type of node found - ignoring
                return False

        # filter only this members that have processes running
        all_members = filter(have_processes, all_members)

        return all_members


class FakeLoopingCall(loopingcall.LoopingCallBase):
    """The fake Looping Call implementation, created for backward
    compatibility with a membership based on DB.
    """
    def __init__(self, driver, host, group):
        self._driver = driver
        self._group = group
        self._host = host

    def stop(self):
        self._driver.leave(self._host, self._group)

    def start(self, interval, initial_delay=None):
        pass

    def wait(self):
        pass
