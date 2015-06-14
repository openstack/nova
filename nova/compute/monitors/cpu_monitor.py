# Copyright 2013 Intel Corporation.
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
CPU monitor to retrieve CPU information
"""

from nova.compute import monitors


class _CPUMonitorBase(monitors.ResourceMonitorBase):
    """CPU monitor base."""

    def _get_cpu_frequency(self, **kwargs):
        """Return CPU current frequency and its timestamp."""
        return None, None

    def _get_cpu_user_time(self, **kwargs):
        """Return CPU user mode time and its timestamp."""
        return None, None

    def _get_cpu_kernel_time(self, **kwargs):
        """Return CPU kernel time and its timestamp."""
        return None, None

    def _get_cpu_idle_time(self, **kwargs):
        """Return CPU idle time and its timestamp."""
        return None, None

    def _get_cpu_iowait_time(self, **kwargs):
        """Return CPU I/O wait time and its timestamp."""
        return None, None

    def _get_cpu_user_percent(self, **kwargs):
        """Return CPU user mode percentage and its timestamp."""
        return None, None

    def _get_cpu_kernel_percent(self, **kwargs):
        """Return CPU kernel percentage and its timestamp."""
        return None, None

    def _get_cpu_idle_percent(self, **kwargs):
        """Return CPU idle percentage and its timestamp."""
        return None, None

    def _get_cpu_iowait_percent(self, **kwargs):
        """Return CPU I/O wait percentage and its timestamp."""
        return None, None

    def _get_cpu_percent(self, **kwargs):
        """Return generic CPU utilization and its timestamp."""
        return None, None
