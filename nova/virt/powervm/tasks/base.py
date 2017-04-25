# Copyright 2016, 2017 IBM Corp.
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
from oslo_log import log as logging
from taskflow import engines as tf_eng
from taskflow.listeners import timing as tf_tm


LOG = logging.getLogger(__name__)


def run(flow, instance=None):
    """Run a TaskFlow Flow with task timing and logging with instance.

    :param flow: A taskflow.flow.Flow to run.
    :param instance: A nova instance, for logging.
    :return: The result of taskflow.engines.run(), a dictionary of named
             results of the Flow's execution.
    """
    def log_with_instance(*args, **kwargs):
        """Wrapper for LOG.info(*args, **kwargs, instance=instance)."""
        if instance is not None:
            kwargs['instance'] = instance
        LOG.info(*args, **kwargs)

    eng = tf_eng.load(flow)
    with tf_tm.PrintingDurationListener(eng, printer=log_with_instance):
        return eng.run()
