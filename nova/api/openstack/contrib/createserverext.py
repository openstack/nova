# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
#    under the License

from nova.api.openstack import create_instance_helper as helper
from nova.api.openstack import extensions
from nova.api.openstack import servers
from nova.api.openstack import wsgi


class Createserverext(extensions.ExtensionDescriptor):
    """The servers create ext

    Exposes addFixedIp and removeFixedIp actions on servers.

    """
    def get_name(self):
        return "Createserverext"

    def get_alias(self):
        return "os-create-server-ext"

    def get_description(self):
        return "Extended support to the Create Server v1.1 API"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/createserverext/api/v1.1"

    def get_updated(self):
        return "2011-07-19T00:00:00+00:00"

    def get_resources(self):
        resources = []

        headers_serializer = servers.HeadersSerializer()
        metadata = servers._get_metadata()
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11),
        }

        body_deserializers = {
            'application/xml': helper.ServerXMLDeserializer(),
        }

        serializer = wsgi.ResponseSerializer(body_serializers,
                                             headers_serializer)
        deserializer = wsgi.RequestDeserializer(body_deserializers)

        res = extensions.ResourceExtension('os-create-server-ext',
                                        controller=servers.ControllerV11(),
                                        deserializer=deserializer,
                                        serializer=serializer)
        resources.append(res)

        return resources
