# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2011 Justin Santa Barbara
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

import sys

from eventlet import event
from eventlet import greenthread

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils

LOG = logging.getLogger(__name__)


class LoopingCallDone(Exception):
    """Exception to break out and stop a LoopingCall.

    The poll-function passed to LoopingCall can raise this exception to
    break out of the loop normally. This is somewhat analogous to
    StopIteration.

    An optional return-value can be included as the argument to the exception;
    this return-value will be returned by LoopingCall.wait()

    """

    def __init__(self, retvalue=True):
        """:param retvalue: Value that LoopingCall.wait() should return."""
        self.retvalue = retvalue


class LoopingCallBase(object):
    def __init__(self, f=None, *args, **kw):
        self.args = args
        self.kw = kw
        self.f = f
        self._running = False
        self.done = None

    def stop(self):
        self._running = False

    def wait(self):
        return self.done.wait()


class FixedIntervalLoopingCall(LoopingCallBase):
    """A fixed interval looping call."""

    def start(self, interval, initial_delay=None):
        self._running = True
        done = event.Event()

        def _inner():
            if initial_delay:
                greenthread.sleep(initial_delay)

            try:
                while self._running:
                    start = timeutils.utcnow()
                    self.f(*self.args, **self.kw)
                    end = timeutils.utcnow()
                    if not self._running:
                        break
                    delay = interval - timeutils.delta_seconds(start, end)
                    if delay <= 0:
                        LOG.warn(_('task run outlasted interval by %s sec') %
                                 -delay)
                    greenthread.sleep(delay if delay > 0 else 0)
            except LoopingCallDone as e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                LOG.exception(_('in fixed duration looping call'))
                done.send_exception(*sys.exc_info())
                return
            else:
                done.send(True)

        self.done = done

        greenthread.spawn_n(_inner)
        return self.done


# TODO(mikal): this class name is deprecated in Havana and should be removed
# in the I release
LoopingCall = FixedIntervalLoopingCall


class DynamicLoopingCall(LoopingCallBase):
    """A looping call which sleeps until the next known event.

    The function called should return how long to sleep for before being
    called again.
    """

    def start(self, initial_delay=None, periodic_interval_max=None):
        self._running = True
        done = event.Event()

        def _inner():
            if initial_delay:
                greenthread.sleep(initial_delay)

            try:
                while self._running:
                    idle = self.f(*self.args, **self.kw)
                    if not self._running:
                        break

                    if periodic_interval_max is not None:
                        idle = min(idle, periodic_interval_max)
                    LOG.debug(_('Dynamic looping call sleeping for %.02f '
                                'seconds'), idle)
                    greenthread.sleep(idle)
            except LoopingCallDone as e:
                self.stop()
                done.send(e.retvalue)
            except Exception:
                LOG.exception(_('in dynamic looping call'))
                done.send_exception(*sys.exc_info())
                return
            else:
                done.send(True)

        self.done = done

        greenthread.spawn(_inner)
        return self.done
