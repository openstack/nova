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

from nova.db import base
from nova import flags
from nova import log as logging
from nova.scheduler import api
from nova import version


FLAGS = flags.FLAGS


LOG = logging.getLogger('nova.manager')


def periodic_task(*args, **kwargs):
    """Decorator to indicate that a method is a periodic task.

    This decorator can be used in two ways:

        1. Without arguments '@periodic_task', this will be run on every tick
           of the periodic scheduler.

        2. With arguments, @periodic_task(ticks_between_runs=N), this will be
           run on every N ticks of the periodic scheduler.
    """
    def decorator(f):
        f._periodic_task = True
        f._ticks_between_runs = kwargs.pop('ticks_between_runs', 0)
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
            cls._ticks_to_skip = cls._ticks_to_skip.copy()
        except AttributeError:
            cls._ticks_to_skip = {}

        for value in cls.__dict__.values():
            if getattr(value, '_periodic_task', False):
                task = value
                name = task.__name__
                cls._periodic_tasks.append((name, task))
                cls._ticks_to_skip[name] = task._ticks_between_runs


class Manager(base.Base):
    __metaclass__ = ManagerMeta

    def __init__(self, host=None, db_driver=None):
        if not host:
            host = FLAGS.host
        self.host = host
        super(Manager, self).__init__(db_driver)

    def periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        for task_name, task in self._periodic_tasks:
            full_task_name = '.'.join([self.__class__.__name__, task_name])

            ticks_to_skip = self._ticks_to_skip[task_name]
            if ticks_to_skip > 0:
                LOG.debug(_("Skipping %(full_task_name)s, %(ticks_to_skip)s"
                            " ticks left until next run"), locals())
                self._ticks_to_skip[task_name] -= 1
                continue

            self._ticks_to_skip[task_name] = task._ticks_between_runs
            LOG.debug(_("Running periodic task %(full_task_name)s"), locals())

            try:
                task(self, context)
            except Exception as e:
                if raise_on_error:
                    raise
                LOG.exception(_("Error during %(full_task_name)s: %(e)s"),
                              locals())

    def init_host(self):
        """Handle initialization if this is a standalone service.

        Child classes should override this method.

        """
        pass

    def service_version(self, context):
        return version.version_string()

    def service_config(self, context):
        config = {}
        for key in FLAGS:
            config[key] = FLAGS.get(key, None)
        return config


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
        super(SchedulerDependentManager, self).__init__(host, db_driver)

    def update_service_capabilities(self, capabilities):
        """Remember these capabilities to send on next periodic update."""
        self.last_capabilities = capabilities

    @periodic_task
    def _publish_service_capabilities(self, context):
        """Pass data back to the scheduler at a periodic interval."""
        if self.last_capabilities:
            LOG.debug(_('Notifying Schedulers of capabilities ...'))
            api.update_service_capabilities(context, self.service_name,
                                self.host, self.last_capabilities)
