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

import copy
import random
import time

from oslo.config import cfg
import six

from nova.openstack.common._i18n import _, _LE, _LI
from nova.openstack.common import log as logging


periodic_opts = [
    cfg.BoolOpt('run_external_periodic_tasks',
                default=True,
                help='Some periodic tasks can be run in a separate process. '
                     'Should we run them here?'),
]

CONF = cfg.CONF
CONF.register_opts(periodic_opts)

LOG = logging.getLogger(__name__)

DEFAULT_INTERVAL = 60.0


def list_opts():
    """Entry point for oslo.config-generator."""
    return [(None, copy.deepcopy(periodic_opts))]


class InvalidPeriodicTaskArg(Exception):
    message = _("Unexpected argument for periodic task creation: %(arg)s.")


def periodic_task(*args, **kwargs):
    """Decorator to indicate that a method is a periodic task.

    This decorator can be used in two ways:

        1. Without arguments '@periodic_task', this will be run on the default
           interval of 60 seconds.

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
            raise InvalidPeriodicTaskArg(arg='ticks_between_runs')

        # Control if run at all
        f._periodic_task = True
        f._periodic_external_ok = kwargs.pop('external_process_ok', False)
        if f._periodic_external_ok and not CONF.run_external_periodic_tasks:
            f._periodic_enabled = False
        else:
            f._periodic_enabled = kwargs.pop('enabled', True)

        # Control frequency
        f._periodic_spacing = kwargs.pop('spacing', 0)
        f._periodic_immediate = kwargs.pop('run_immediately', False)
        if f._periodic_immediate:
            f._periodic_last_run = None
        else:
            f._periodic_last_run = time.time()
        return f

    # NOTE(sirp): The `if` is necessary to allow the decorator to be used with
    # and without parenthesis.
    #
    # In the 'with-parenthesis' case (with kwargs present), this function needs
    # to return a decorator function since the interpreter will invoke it like:
    #
    #   periodic_task(*args, **kwargs)(f)
    #
    # In the 'without-parenthesis' case, the original function will be passed
    # in as the first argument, like:
    #
    #   periodic_task(f)
    if kwargs:
        return decorator
    else:
        return decorator(args[0])


class _PeriodicTasksMeta(type):
    def __init__(cls, names, bases, dict_):
        """Metaclass that allows us to collect decorated periodic tasks."""
        super(_PeriodicTasksMeta, cls).__init__(names, bases, dict_)

        # NOTE(sirp): if the attribute is not present then we must be the base
        # class, so, go ahead an initialize it. If the attribute is present,
        # then we're a subclass so make a copy of it so we don't step on our
        # parent's toes.
        try:
            cls._periodic_tasks = cls._periodic_tasks[:]
        except AttributeError:
            cls._periodic_tasks = []

        try:
            cls._periodic_spacing = cls._periodic_spacing.copy()
        except AttributeError:
            cls._periodic_spacing = {}

        for value in cls.__dict__.values():
            if getattr(value, '_periodic_task', False):
                task = value
                name = task.__name__

                if task._periodic_spacing < 0:
                    LOG.info(_LI('Skipping periodic task %(task)s because '
                                 'its interval is negative'),
                             {'task': name})
                    continue
                if not task._periodic_enabled:
                    LOG.info(_LI('Skipping periodic task %(task)s because '
                                 'it is disabled'),
                             {'task': name})
                    continue

                # A periodic spacing of zero indicates that this task should
                # be run on the default interval to avoid running too
                # frequently.
                if task._periodic_spacing == 0:
                    task._periodic_spacing = DEFAULT_INTERVAL

                cls._periodic_tasks.append((name, task))
                cls._periodic_spacing[name] = task._periodic_spacing


def _nearest_boundary(last_run, spacing):
    """Find nearest boundary which is in the past, which is a multiple of the
    spacing with the last run as an offset.

    Eg if last run was 10 and spacing was 7, the new last run could be: 17, 24,
    31, 38...

    0% to 5% of the spacing value will be added to this value to ensure tasks
    do not synchronize. This jitter is rounded to the nearest second, this
    means that spacings smaller than 20 seconds will not have jitter.
    """
    current_time = time.time()
    if last_run is None:
        return current_time
    delta = current_time - last_run
    offset = delta % spacing
    # Add up to 5% jitter
    jitter = int(spacing * (random.random() / 20))
    return current_time - offset + jitter


@six.add_metaclass(_PeriodicTasksMeta)
class PeriodicTasks(object):
    def __init__(self):
        super(PeriodicTasks, self).__init__()
        self._periodic_last_run = {}
        for name, task in self._periodic_tasks:
            self._periodic_last_run[name] = task._periodic_last_run

    def run_periodic_tasks(self, context, raise_on_error=False):
        """Tasks to be run at a periodic interval."""
        idle_for = DEFAULT_INTERVAL
        for task_name, task in self._periodic_tasks:
            full_task_name = '.'.join([self.__class__.__name__, task_name])

            spacing = self._periodic_spacing[task_name]
            last_run = self._periodic_last_run[task_name]

            # Check if due, if not skip
            idle_for = min(idle_for, spacing)
            if last_run is not None:
                delta = last_run + spacing - time.time()
                if delta > 0:
                    idle_for = min(idle_for, delta)
                    continue

            LOG.debug("Running periodic task %(full_task_name)s",
                      {"full_task_name": full_task_name})
            self._periodic_last_run[task_name] = _nearest_boundary(
                last_run, spacing)

            try:
                task(self, context)
            except Exception as e:
                if raise_on_error:
                    raise
                LOG.exception(_LE("Error during %(full_task_name)s: %(e)s"),
                              {"full_task_name": full_task_name, "e": e})
            time.sleep(0)

        return idle_for
