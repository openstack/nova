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

# The APIRouterV21 moves down to the 'nova.api.openstack.compute.routes' for
# circle reference problem. Import the APIRouterV21 is for the api-paste.ini
# works correctly without modification. We still looking for a chance to move
# the APIRouterV21 back to here after cleanups.
from nova.api.openstack.compute.routes import APIRouterV21  # noqa
