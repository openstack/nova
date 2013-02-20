# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""Base Manager class.

Managers are responsible for a certain aspect of the system.  It is a logical
grouping of code relating to a portion of the system.  In general other
components should be using the manager to make changes to the components that
it is responsible for.

For example, other components that need to deal with volumes in some way,
should do so by calling methods on the VolumeManager instead of directly
changing fields in the database.  This allows us to keep all of the code
relating to volumes in the same place.

We have adopted a basic strategy of Smart managers and dumb data, which means
rather than attaching methods to data objects, components should call manager
methods that act on the data.

Methods on managers that can be executed locally should be called directly. If
a particular method must execute on a remote host, this should be done via rpc
to the service that wraps the manager

Managers should be responsible for most of the db access, and
non-implementation specific data.  Anything implementation specific that can't
be generalized should be done by the Driver.

In general, we prefer to have one manager with multiple drivers for different
implementations, but sometimes it makes sense to have multiple managers.  You
can think of it this way: Abstract different overall strategies at the manager
level(FlatNetwork vs VlanNetwork), and different implementations at the driver
level(LinuxNetDriver vs CiscoNetDriver).

Managers will often provide methods for initial setup of a host or periodic
tasks to a wrapping service.

This module provides Manager, a base class for managers.

"""

import time

import eventlet
from oslo.config import cfg

from nova.db import base
from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common.plugin import pluginmanager
from nova.openstack.common.rpc import dispatcher as rpc_dispatcher
from nova.scheduler import rpcapi as scheduler_rpcapi


periodic_opts = [
    cfg.BoolOpt('run_external_periodic_tasks',
               default=True,
               help=('Some periodic tasks can be run in a separate process. '
                     'Should we run them here?')),
    ]

CONF = cfg.CONF
CONF.register_opts(periodic_opts)
CONF.import_opt('host', 'nova.netconf')
LOG = logging.getLogger(__name__)

DEFAULT_INTERVAL = 60.0


def periodic_task(*args, **kwargs):
    """Decorator to indicate that a method is a periodic task.

    This decorator can be used in two ways:

        1. Without arguments '@periodic_task', this will be run on every cycle
           of the periodic scheduler.

        2. With arguments:
           @periodic_task(spacing=N [, run_immediately=[True|False]])
           this will be run on approximately every N seconds. If this number is
           negative the periodic task will be disabled. If the run_immediately
           argument is provided and has a value of 'True', the first run of the
           task will be shortly after task scheduler starts.  If
           run_immediately is omitted or set to 'False', the first time the
           task runs will be approximately N seconds after the task scheduler
           starts.
    """
    def decorator(f):
        # Test for old style invocation
        if 'ticks_between_runs' in kwargs:
            raise exception.InvalidPeriodicTaskArg(arg='ticks_between_runs')

        # Control if run at all
        f._periodic_task = True
        f._periodic_external_ok = kwargs.pop('external_process_ok', False)
        if f._periodic_external_ok and not CONF.run_external_periodic_tasks:
            f._periodic_enabled = False
        else:
            f._periodic_enabled = kwargs.pop('enabled', True)

        # Control frequency
        f._periodic_spacing = kwargs.pop('spacing', 0)
        if kwargs.pop('run_immediately', False):
            f._periodic_last_run = None
        else:
            f._periodic_last_run = time.time()
        return f

    # NOTE(sirp): The `if` is necessary to allow the decorator to be used with
    # and without parens.
    #
    # In the 'with-parens' case (with kwargs present), this function needs to
    # return a decorator function since the interpreter will invoke it like:
    #
    #   periodic_task(*args, **kwargs)(f)
    #
    # In the 'without-parens' case, the original function will be passed
    # in as the first argument, like:
    #
    #   periodic_task(f)
    if kwargs:
        return decorator
    else:
        return decorator(args[0])


class ManagerMeta(type):
    def __init__(cls, names, bases, dict_):
        """Metaclass that allows us to collect decorated periodic tasks."""
        super(ManagerMeta, cls).__init__(names, bases, dict_)

        # NOTE(sirp): if the attribute is not present then we must be the base
        # class, so, go ahead an initialize it. If the attribute is present,
        # then we're a subclass so make a copy of it so we don't step on our
        # parent's toes.
        try:
            cls._periodic_tasks = cls._periodic_tasks[:]
        except AttributeError:
            cls._periodic_tasks = []

        try:
            cls._periodic_last_run = cls._periodic_last_run.copy()
        except AttributeError:
            cls._periodic_last_run = {}

        try:
            cls._periodic_spacing = cls._periodic_spacing.copy()
        except AttributeError:
            cls._periodic_spacing = {}

        for value in cls.__dict__.values():
            if getattr(value, '_periodic_task', False):
                task = value
                name = task.__name__

                if task._periodic_spacing < 0:
                    LOG.info(_('Skipping periodic task %(task)s because '
                               'its interval is negative'),
                             {'task': name})
                    continue
                if not task._periodic_enabled:
                    LOG.info(_('Skipping periodic task %(task)s because '
                               'it is disabled'),
                             {'task': name})
                    continue

                # A periodic spacing of zero indicates that this task should
                # be run every pass
                if task._periodic_spacing == 0:
                    task._periodic_spacing = None

                cls._periodic_tasks.append((name, task))
                cls._periodic_spacing[name] = task._periodic_spacing
                cls._periodic_last_run[name] = task._periodic_last_run


class Manager(base.Base):
    __metaclass__ = ManagerMeta

    # Set RPC API version to 1.0 by default.
    RPC_API_VERSION = '1.0'

    def __init__(self, host=None, db_driver=None):
        if not host:
            host = CONF.host
        self.host = host
        self.load_plugins()
        self.backdoor_port = None
        super(Manager, self).__init__(db_driver)

    def load_plugins(self):
        pluginmgr = pluginmanager.PluginManager('nova', self.__class__)
        pluginmgr.load_plugins()

    def create_rpc_dispatcher(self):
        '''Get the rpc dispatcher for this manager.

        If a manager would like to set an rpc API version, or support more than
        one class as the target of rpc messages, override this method.
        '''
        return rpc_dispatcher.RpcDispatcher([self])

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        idle_for = DEFAULT_INTERVAL
        for task_name, task in self._periodic_tasks:
            full_task_name = '.'.join([self.__class__.__name__, task_name])

            # If a periodic task is _nearly_ due, then we'll run it early
            if self._periodic_spacing[task_name] is None:
                wait = 0
            elif self._periodic_last_run[task_name] is None:
                wait = 0
            else:
                due = (self._periodic_last_run[task_name] +
                       self._periodic_spacing[task_name])
                wait = max(0, due - time.time())
                if wait > 0.2:
                    if wait < idle_for:
                        idle_for = wait
                    continue

            LOG.debug(_("Running periodic task %(full_task_name)s"), locals())
            self._periodic_last_run[task_name] = time.time()

            try:
                task(self, context)
            except Exception as e:
                if raise_on_error:
                    raise
                LOG.exception(_("Error during %(full_task_name)s: %(e)s"),
                              locals())

            if (not self._periodic_spacing[task_name] is None and
                self._periodic_spacing[task_name] < idle_for):
                idle_for = self._periodic_spacing[task_name]
            eventlet.sleep(0)

        return idle_for

    def init_host(self):
        """Hook to do additional manager initialization when one requests
        the service be started.  This is called before any service record
        is created.

        Child classes should override this method.
        """
        pass

    def pre_start_hook(self, **kwargs):
        """Hook to provide the manager the ability to do additional
        start-up work before any RPC queues/consumers are created. This is
        called after other initialization has succeeded and a service
        record is created.

        Child classes should override this method.
        """
        pass

    def post_start_hook(self):
        """Hook to provide the manager the ability to do additional
        start-up work immediately after a service creates RPC consumers
        and starts 'running'.

        Child classes should override this method.
        """
        pass


class SchedulerDependentManager(Manager):
    """Periodically send capability updates to the Scheduler services.

    Services that need to update the Scheduler of their capabilities
    should derive from this class. Otherwise they can derive from
    manager.Manager directly. Updates are only sent after
    update_service_capabilities is called with non-None values.

    """

    def __init__(self, host=None, db_driver=None, service_name='undefined'):
        self.last_capabilities = None
        self.service_name = service_name
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        super(SchedulerDependentManager, self).__init__(host, db_driver)

    def load_plugins(self):
        pluginmgr = pluginmanager.PluginManager('nova', self.service_name)
        pluginmgr.load_plugins()

    def update_service_capabilities(self, capabilities):
        """Remember these capabilities to send on next periodic update."""
        if not isinstance(capabilities, list):
            capabilities = [capabilities]
        self.last_capabilities = capabilities

    @periodic_task
    def publish_service_capabilities(self, context):
        """Pass data back to the scheduler.

        Called at a periodic interval. And also called via rpc soon after
        the start of the scheduler.
        """
        if self.last_capabilities:
            LOG.debug(_('Notifying Schedulers of capabilities ...'))
            self.scheduler_rpcapi.update_service_capabilities(context,
                    self.service_name, self.host, self.last_capabilities)
