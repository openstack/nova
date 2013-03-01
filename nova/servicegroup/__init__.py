# Copyright 2012 IBM Corp.
# Copyright (c) AT&T Labs Inc. 2012 Yun Mao <yunmao@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
The membership service for Nova. Different implementations can be plugged
according to the Nova configuration.
"""

from nova.servicegroup import api

API = api.API
