# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import eventlet
from oslo_utils import importutils
from six.moves import reload_module

from nova import debugger

if debugger.enabled():
    # turn off thread patching to enable the remote debugger
    eventlet.monkey_patch(os=False, thread=False)
else:
    eventlet.monkey_patch(os=False)

# NOTE(rgerganov): oslo.context is storing a global thread-local variable
# which keeps the request context for the current thread. If oslo.context is
# imported before calling monkey_patch(), then this thread-local won't be
# green. To workaround this, reload the module after calling monkey_patch()
reload_module(importutils.import_module('oslo_context.context'))
