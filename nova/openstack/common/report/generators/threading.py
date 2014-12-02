# Copyright 2013 Red Hat, Inc.
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

"""Provides thread-related generators

This module defines classes for threading-related
generators for generating the models in
:mod:`openstack.common.report.models.threading`.
"""

import sys

import greenlet

from nova.openstack.common.report.models import threading as tm
from nova.openstack.common.report.models import with_default_views as mwdv
from nova.openstack.common.report import utils as rutils
from nova.openstack.common.report.views.text import generic as text_views


class ThreadReportGenerator(object):
    """A Thread Data Generator

    This generator returns a collection of
    :class:`openstack.common.report.models.threading.ThreadModel`
    objects by introspecting the current python state using
    :func:`sys._current_frames()` .
    """

    def __call__(self):
        threadModels = [
            tm.ThreadModel(thread_id, stack)
            for thread_id, stack in sys._current_frames().items()
        ]

        return mwdv.ModelWithDefaultViews(threadModels,
                                          text_view=text_views.MultiView())


class GreenThreadReportGenerator(object):
    """A Green Thread Data Generator

    This generator returns a collection of
    :class:`openstack.common.report.models.threading.GreenThreadModel`
    objects by introspecting the current python garbage collection
    state, and sifting through for :class:`greenlet.greenlet` objects.

    .. seealso::

        Function :func:`openstack.common.report.utils._find_objects`
    """

    def __call__(self):
        threadModels = [
            tm.GreenThreadModel(gr.gr_frame)
            for gr in rutils._find_objects(greenlet.greenlet)
        ]

        return mwdv.ModelWithDefaultViews(threadModels,
                                          text_view=text_views.MultiView())
