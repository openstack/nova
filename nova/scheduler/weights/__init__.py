# Copyright (c) 2011 OpenStack Foundation
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
Scheduler host weights
"""

from oslo.config import cfg

from nova import weights

CONF = cfg.CONF


class WeighedHost(weights.WeighedObject):
    def to_dict(self):
        x = dict(weight=self.weight)
        x['host'] = self.obj.host
        return x

    def __repr__(self):
        return "WeighedHost [host: %r, weight: %s]" % (
                self.obj, self.weight)


class BaseHostWeigher(weights.BaseWeigher):
    """Base class for host weights."""
    pass


class HostWeightHandler(weights.BaseWeightHandler):
    object_class = WeighedHost

    def __init__(self):
        super(HostWeightHandler, self).__init__(BaseHostWeigher)


def all_weighers():
    """Return a list of weight plugin classes found in this directory."""
    return HostWeightHandler().get_all_classes()


class FaultToleranceHost(object):
    def __init__(self, obj):
        self.obj = obj

    def __getattr__(self, name):
        return getattr(self.obj, name)

    def to_dict(self):
        return dict(host=self.obj.host)

    def __repr__(self):
        return "FaultToleranceHost [host: %s]" % self.obj.host


class FaultToleranceWeighedHosts(object):
    def __init__(self, obj, weight):
        self.obj = []
        for host in obj:
            self.obj.append(FaultToleranceHost(host))
        self.weight = weight

    def __iter__(self):
        return iter(self.obj)

    def __getitem__(self, key):
        return self.obj[key]

    def __len__(self):
        return len(self.obj)

    def to_dict(self):
        x = dict(weight=self.weight)
        x['hosts'] = self.obj.to_dict()
        return x

    def __repr__(self):
        return "<FTWeighedHosts '%s' - Weight: %s>" % (self.obj, self.weight)


class FaultToleranceBaseHostWeigher(weights.BaseWeigher):
    pass


class FaultToleranceHostWeightHandler(weights.BaseWeightHandler):
    """A new weight handler for sets of hosts rather than single hosts.

    Weighers used by this class should extend FaultToleranceBaseHostWeigher.

    Note that the hostsets are passed together in an object to achieve
    compability with the normal weighing functionality.
    """
    object_class = FaultToleranceWeighedHosts

    def __init__(self):
        (super(FaultToleranceHostWeightHandler, self).
            __init__(FaultToleranceBaseHostWeigher))


def ft_all_weighers():
    return FaultToleranceHostWeightHandler().get_all_classes()
