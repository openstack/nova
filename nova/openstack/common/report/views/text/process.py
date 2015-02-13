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

"""Provides process view

This module provides a view for
visualizing processes in human-readable formm
"""

import nova.openstack.common.report.views.jinja_view as jv


class ProcessView(jv.JinjaView):
    """A Process View

    This view displays process models defined by
    :class:`openstack.common.report.models.process.ProcessModel`
    """

    VIEW_TEXT = (
        "Process {{ pid }} (under {{ parent_pid }}) "
        "[ run by: {{ username }} ({{ uids.real|default('unknown uid') }}),"
        " state: {{ state }} ]\n"
        "{% for child in children %}"
        "    {{ child }}"
        "{% endfor %}"
    )
