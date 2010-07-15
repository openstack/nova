# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
Get our vendor folders into the system path.
"""

import os
import sys

# abspath/__file__/../vendor
VENDOR_PATH = os.path.abspath(
    os.path.join(os.path.dirname(os.path.dirname(__file__)), 'vendor'))

if not os.path.exists(VENDOR_PATH):
    print 'warning: no vendor libraries included'
else:
  paths = [VENDOR_PATH,
           os.path.join(VENDOR_PATH, 'pymox'),
           os.path.join(VENDOR_PATH, 'tornado'),
           os.path.join(VENDOR_PATH, 'python-gflags'),
           os.path.join(VENDOR_PATH, 'python-daemon'),
           os.path.join(VENDOR_PATH, 'lockfile'),
           os.path.join(VENDOR_PATH, 'boto'),
           os.path.join(VENDOR_PATH, 'Twisted-10.0.0'),
           os.path.join(VENDOR_PATH, 'redis-py'),
           ]

  for p in paths:
    if p not in sys.path:
      sys.path.insert(0, p)
