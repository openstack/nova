#    Copyright 2012 IBM Corp.
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

import contextlib


class VirtAPI(object):
    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        raise NotImplementedError()

    def update_compute_provider_status(self, context, rp_uuid, enabled):
        """Used to add/remove the COMPUTE_STATUS_DISABLED trait on the provider

        :param context: nova auth RequestContext
        :param rp_uuid: UUID of a compute node resource provider in Placement
        :param enabled: True if the node is enabled in which case the trait
            would be removed, False if the node is disabled in which case
            the trait would be added.
        """
        raise NotImplementedError()
