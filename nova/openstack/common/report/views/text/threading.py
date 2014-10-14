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

"""Provides thread and stack-trace views

This module provides a collection of views for
visualizing threads, green threads, and stack traces
in human-readable form.
"""

from nova.openstack.common.report.views import jinja_view as jv


class StackTraceView(jv.JinjaView):
    """A Stack Trace View

    This view displays stack trace models defined by
    :class:`openstack.common.report.models.threading.StackTraceModel`
    """

    VIEW_TEXT = (
        "{% if root_exception is not none %}"
        "Exception: {{ root_exception }}\n"
        "------------------------------------\n"
        "\n"
        "{% endif %}"
        "{% for line in lines %}\n"
        "{{ line.filename }}:{{ line.line }} in {{ line.name }}\n"
        "    {% if line.code is not none %}"
        "`{{ line.code }}`"
        "{% else %}"
        "(source not found)"
        "{% endif %}\n"
        "{% else %}\n"
        "No Traceback!\n"
        "{% endfor %}"
    )


class GreenThreadView(object):
    """A Green Thread View

    This view displays a green thread provided by the data
    model :class:`openstack.common.report.models.threading.GreenThreadModel`
    """

    FORMAT_STR = "------{thread_str: ^60}------" + "\n" + "{stack_trace}"

    def __call__(self, model):
        return self.FORMAT_STR.format(
            thread_str=" Green Thread ",
            stack_trace=model.stack_trace
        )


class ThreadView(object):
    """A Thread Collection View

    This view displays a python thread provided by the data
    model :class:`openstack.common.report.models.threading.ThreadModel`  # noqa
    """

    FORMAT_STR = "------{thread_str: ^60}------" + "\n" + "{stack_trace}"

    def __call__(self, model):
        return self.FORMAT_STR.format(
            thread_str=" Thread #{0} ".format(model.thread_id),
            stack_trace=model.stack_trace
        )
