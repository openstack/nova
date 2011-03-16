# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova import db
from nova import context
from nova.api.openstack import faults
from nova.api.openstack import common
from nova.compute import instance_types
from nova import wsgi
import nova.api.openstack


class Controller(wsgi.Controller):
    """Flavor controller for the OpenStack API."""

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "flavor": ["id", "name", "ram", "disk"]}}}

    def index(self, req):
        """Return all flavors in brief."""
        return dict(flavors=[dict(id=flavor['flavorid'], name=flavor['name'])
                             for flavor in self.detail(req)['flavors']])

    def detail(self, req):
        """Return all flavors in detail."""
        items = [self.show(req, id)['flavor'] for id in self._all_ids(req)]
        return dict(flavors=items)

    def show(self, req, id):
        """Return data about the given flavor id."""
        ctxt = req.environ['nova.context']
        values = db.instance_type_get_by_flavor_id(ctxt, id)
        values.update({'id': values['flavorid']})
        return dict(flavor=values)
        raise faults.Fault(exc.HTTPNotFound())

    def _all_ids(self, req):
        """Return the list of all flavorids."""
        ctxt = req.environ['nova.context']
        inst_types = db.instance_type_get_all(ctxt)
        flavor_ids = [inst_types[i]['flavorid'] for i in inst_types.keys()]
        return sorted(flavor_ids)
