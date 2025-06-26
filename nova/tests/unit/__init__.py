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

# The import order in the test environment is different from the import
# order in a real env. During unit testing nova.test.unit is imported first
# to discover the unit tests, then the modules under it are imported. This
# test discovery import forces the import of oslo.messaging eventually that
# import time run code that uses the oslo.service backend which forces the
# initialization of the backed to the default eventlet. This prevents
# our tests to run with the threading backend. To avoid this we force the
# backend registration early here by using our common monkey_patch mode
# that already does smart backend selection based on env variables.
# The monkey_patching would be used anyhow when nova.test is imported so
# this does not change the end result just the order of imports
# autopep8: off
from nova import monkey_patch ; monkey_patch.patch()  # noqa
# autopep8: on

from nova import objects

# NOTE(comstud): Make sure we have all of the objects loaded. We do this
# at module import time, because we may be using mock decorators in our
# tests that run at import time.
objects.register_all()
