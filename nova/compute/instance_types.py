# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
The built-in instance properties.
"""

INSTANCE_TYPES = {
    'm1.tiny': dict(memory_mb=512, vcpus=1, local_gb=0, flavorid=1),
    'm1.small': dict(memory_mb=1024, vcpus=1, local_gb=10, flavorid=2),
    'm1.medium': dict(memory_mb=2048, vcpus=2, local_gb=10, flavorid=3),
    'm1.large': dict(memory_mb=4096, vcpus=4, local_gb=10, flavorid=4),
    'm1.xlarge': dict(memory_mb=8192, vcpus=4, local_gb=10, flavorid=5),
    'c1.medium': dict(memory_mb=2048, vcpus=4, local_gb=10, flavorid=6)}
