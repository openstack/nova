# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
"""Example Module for testing utils.monkey_patch()."""


CALLED_FUNCTION = []


def example_decorator(name, function):
    """ decorator for notify which is used from utils.monkey_patch()

        :param name: name of the function
        :param function: - object of the function
        :returns: function -- decorated function
    """
    def wrapped_func(*args, **kwarg):
        CALLED_FUNCTION.append(name)
        return function(*args, **kwarg)
    return wrapped_func
