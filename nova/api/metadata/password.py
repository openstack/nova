# Copyright 2012 Nebula, Inc.
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

from webob import exc

from nova import context
from nova import db


MAX_SIZE = 256


def handle_password(req, meta_data):
    ctxt = context.get_admin_context()
    password = meta_data.password
    if req.method == 'GET':
        return meta_data.password
    elif req.method == 'POST':
        # NOTE(vish): The conflict will only happen once the metadata cache
        #             updates, but it isn't a huge issue if it can be set for
        #             a short window.
        if meta_data.password:
            raise exc.HTTPConflict()
        if (req.content_length > MAX_SIZE or len(req.body) > MAX_SIZE):
            msg = _("Request is too large.")
            raise exc.HTTPBadRequest(explanation=msg)
        db.instance_system_metadata_update(ctxt,
                                           meta_data.uuid,
                                           {'password': req.body},
                                           False)
    else:
        raise exc.HTTPBadRequest()
