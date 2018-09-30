# Copyright 2010-2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
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

from oslo_utils import strutils

from nova.api.openstack import common
from nova.image import glance
from nova import utils


class ViewBuilder(common.ViewBuilder):

    _collection_name = "images"

    def basic(self, request, image):
        """Return a dictionary with basic image attributes."""
        return {
            "image": {
                "id": image.get("id"),
                "name": image.get("name"),
                "links": self._get_links(request,
                                         image["id"],
                                         self._collection_name),
            },
        }

    def show(self, request, image):
        """Return a dictionary with image details."""
        image_dict = {
            "id": image.get("id"),
            "name": image.get("name"),
            "minRam": int(image.get("min_ram") or 0),
            "minDisk": int(image.get("min_disk") or 0),
            "metadata": image.get("properties", {}),
            "created": self._format_date(image.get("created_at")),
            "updated": self._format_date(image.get("updated_at")),
            "status": self._get_status(image),
            "progress": self._get_progress(image),
            "OS-EXT-IMG-SIZE:size": image.get("size"),
            "links": self._get_links(request,
                                     image["id"],
                                     self._collection_name),
        }

        instance_uuid = image.get("properties", {}).get("instance_uuid")

        if instance_uuid is not None:
            server_ref = self._get_href_link(request, instance_uuid, 'servers')
            image_dict["server"] = {
                "id": instance_uuid,
                "links": [{
                    "rel": "self",
                    "href": server_ref,
                },
                {
                    "rel": "bookmark",
                    "href": self._get_bookmark_link(request,
                                                    instance_uuid,
                                                    'servers'),
                }],
            }

        auto_disk_config = image_dict['metadata'].get("auto_disk_config", None)
        if auto_disk_config is not None:
            value = strutils.bool_from_string(auto_disk_config)
            image_dict["OS-DCF:diskConfig"] = (
                'AUTO' if value else 'MANUAL')

        return dict(image=image_dict)

    def detail(self, request, images):
        """Show a list of images with details."""
        list_func = self.show
        coll_name = self._collection_name + '/detail'
        return self._list_view(list_func, request, images, coll_name)

    def index(self, request, images):
        """Show a list of images with basic attributes."""
        list_func = self.basic
        coll_name = self._collection_name
        return self._list_view(list_func, request, images, coll_name)

    def _list_view(self, list_func, request, images, coll_name):
        """Provide a view for a list of images.

        :param list_func: Function used to format the image data
        :param request: API request
        :param images: List of images in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query

        :returns: Image reply data in dictionary format
        """
        image_list = [list_func(request, image)["image"] for image in images]
        images_links = self._get_collection_links(request, images, coll_name)
        images_dict = dict(images=image_list)

        if images_links:
            images_dict["images_links"] = images_links

        return images_dict

    def _get_links(self, request, identifier, collection_name):
        """Return a list of links for this image."""
        return [{
            "rel": "self",
            "href": self._get_href_link(request, identifier, collection_name),
        },
        {
            "rel": "bookmark",
            "href": self._get_bookmark_link(request,
                                            identifier,
                                            collection_name),
        },
        {
            "rel": "alternate",
            "type": "application/vnd.openstack.image",
            "href": self._get_alternate_link(request, identifier),
        }]

    def _get_alternate_link(self, request, identifier):
        """Create an alternate link for a specific image id."""
        glance_url = glance.generate_glance_url(
            request.environ['nova.context'])
        glance_url = self._update_glance_link_prefix(glance_url)
        return '/'.join([glance_url,
                         self._collection_name,
                         str(identifier)])

    @staticmethod
    def _format_date(dt):
        """Return standard format for a given datetime object."""
        if dt is not None:
            return utils.isotime(dt)

    @staticmethod
    def _get_status(image):
        """Update the status field to standardize format."""
        return {
            'active': 'ACTIVE',
            'queued': 'SAVING',
            'saving': 'SAVING',
            'deleted': 'DELETED',
            'pending_delete': 'DELETED',
            'killed': 'ERROR',
        }.get(image.get("status"), 'UNKNOWN')

    @staticmethod
    def _get_progress(image):
        return {
            "queued": 25,
            "saving": 50,
            "active": 100,
        }.get(image.get("status"), 0)
