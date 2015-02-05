# Copyright 2014 Red Hat, Inc.
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

"""Provides process-data generators

This modules defines a class for generating
process data by way of the psutil package.
"""

import os

import psutil

from nova.openstack.common.report.models import process as pm


class ProcessReportGenerator(object):
    """A Process Data Generator

    This generator returns a
    :class:`openstack.common.report.models.process.ProcessModel`
    based on the current process (which will also include
    all subprocesses, recursively) using the :class:`psutil.Process` class`.
    """

    def __call__(self):
        return pm.ProcessModel(psutil.Process(os.getpid()))
