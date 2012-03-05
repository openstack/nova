# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack, LLC
# Copyright 2011 Canonical Ltd.
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

"""The Flavor extra data extension

Openstack API version 1.1 lists "name", "ram", "disk", "vcpus" as flavor
attributes.  This extension adds to that list:

- OS-FLV-EXT-DATA:ephemeral
"""

from nova import exception
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import instance_types


authorize = extensions.soft_extension_authorizer('compute', 'flavorextradata')


class FlavorextradataController(wsgi.Controller):
    def _get_flavor_refs(self):
        """Return a dictionary mapping flavorid to flavor_ref."""
        flavor_refs = instance_types.get_all_types(True)
        rval = {}
        for name, obj in flavor_refs.iteritems():
            rval[obj['flavorid']] = obj
        return rval

    def _extend_flavor(self, flavor_rval, flavor_ref):
        key = "%s:ephemeral" % (Flavorextradata.alias)
        flavor_rval[key] = flavor_ref['ephemeral_gb']

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorextradatumTemplate())

            try:
                flavor_ref = instance_types.\
                                get_instance_type_by_flavor_id(id)
            except exception.FlavorNotFound:
                explanation = _("Flavor not found.")
                raise exception.HTTPNotFound(explanation=explanation)

            self._extend_flavor(resp_obj.obj['flavor'], flavor_ref)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorextradataTemplate())

            flavors = list(resp_obj.obj['flavors'])
            flavor_refs = self._get_flavor_refs()

            for flavor_rval in flavors:
                flavor_ref = flavor_refs[flavor_rval['id']]
                self._extend_flavor(flavor_rval, flavor_ref)

    @wsgi.extends(action='create')
    def create(self, req, body, resp_obj):
        context = req.environ['nova.context']
        if authorize(context):
            # Attach our slave template to the response object
            resp_obj.attach(xml=FlavorextradatumTemplate())

            try:
                fid = resp_obj.obj['flavor']['id']
                flavor_ref = instance_types.get_instance_type_by_flavor_id(fid)
            except exception.FlavorNotFound:
                explanation = _("Flavor not found.")
                raise exception.HTTPNotFound(explanation=explanation)

            self._extend_flavor(resp_obj.obj['flavor'], flavor_ref)


class Flavorextradata(extensions.ExtensionDescriptor):
    """Provide additional data for flavors"""

    name = "FlavorExtraData"
    alias = "OS-FLV-EXT-DATA"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "flavor_extra_data/api/v1.1")
    updated = "2011-09-14T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = FlavorextradataController()
        extension = extensions.ControllerExtension(self, 'flavors', controller)
        return [extension]


def make_flavor(elem):
    elem.set('{%s}ephemeral' % Flavorextradata.namespace,
             '%s:ephemeral' % Flavorextradata.alias)


class FlavorextradatumTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavor', selector='flavor')
        make_flavor(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Flavorextradata.alias: Flavorextradata.namespace})


class FlavorextradataTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('flavors')
        elem = xmlutil.SubTemplateElement(root, 'flavor', selector='flavors')
        make_flavor(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Flavorextradata.alias: Flavorextradata.namespace})
