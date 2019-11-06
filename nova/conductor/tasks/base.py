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
import functools

from oslo_utils import excutils
import six


def rollback_wrapper(original):
    @functools.wraps(original)
    def wrap(self):
        try:
            return original(self)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                self.rollback(ex)
    return wrap


@six.add_metaclass(abc.ABCMeta)
class TaskBase(object):

    def __init__(self, context, instance):
        self.context = context
        self.instance = instance

    @rollback_wrapper
    def execute(self):
        """Run task's logic, written in _execute() method
        """
        return self._execute()

    @abc.abstractmethod
    def _execute(self):
        """Descendants should place task's logic here, while resource
        initialization should be performed over __init__
        """
        pass

    def rollback(self, ex):
        """Rollback failed task
        Descendants should implement this method to allow task user to
        rollback status to state before execute method  was call
        """
        pass
