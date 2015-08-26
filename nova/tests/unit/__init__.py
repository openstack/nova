# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
:mod:`nova.tests.unit` -- Nova Unittests
=====================================================

.. automodule:: nova.tests.unit
   :platform: Unix
"""

import eventlet

from nova import objects

eventlet.monkey_patch(os=False)

# NOTE(alaski): Make sure this is done after eventlet monkey patching otherwise
# the threading.local() store used in oslo_messaging will be initialized to
# threadlocal storage rather than greenthread local.  This will cause context
# sets and deletes in that storage to clobber each other.
# NOTE(comstud): Make sure we have all of the objects loaded. We do this
# at module import time, because we may be using mock decorators in our
# tests that run at import time.
objects.register_all()
