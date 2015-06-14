# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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


import abc

import six


@six.add_metaclass(abc.ABCMeta)
class Resource(object):
    """This base class defines the interface used for compute resource
    plugins. It is not necessary to use this base class, but all compute
    resource plugins must implement the abstract methods found here.
    An instance of the plugin object is instantiated when it is loaded
    by calling __init__() with no parameters.
    """

    @abc.abstractmethod
    def reset(self, resources, driver):
        """Set the resource to an initial state based on the resource
        view discovered from the hypervisor.
        """
        pass

    @abc.abstractmethod
    def test(self, usage, limits):
        """Test to see if we have sufficient resources to allocate for
        an instance with the given resource usage.

        :param usage: the resource usage of the instances
        :param limits: limits to apply

        :returns: None if the test passes or a string describing the reason
                  why the test failed
        """
        pass

    @abc.abstractmethod
    def add_instance(self, usage):
        """Update resource information adding allocation according to the
        given resource usage.

        :param usage: the resource usage of the instance being added

        :returns: None
        """
        pass

    @abc.abstractmethod
    def remove_instance(self, usage):
        """Update resource information removing allocation according to the
        given resource usage.

        :param usage: the resource usage of the instance being removed

        :returns: None

        """
        pass

    @abc.abstractmethod
    def write(self, resources):
        """Write resource data to populate resources.

        :param resources: the resources data to be populated

        :returns: None
        """
        pass

    @abc.abstractmethod
    def report_free(self):
        """Log free resources.

        This method logs how much free resource is held by
        the resource plugin.

        :returns: None
        """
        pass
