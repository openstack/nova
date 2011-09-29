# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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

import os.path

from nova.api.openstack import common
from nova import utils


class ViewBuilder(object):
    """Base class for generating responses to OpenStack API image requests."""

    def __init__(self, base_url, project_id=""):
        """Initialize new `ViewBuilder`."""
        self.base_url = base_url
        self.project_id = project_id

    def _format_dates(self, image):
        """Update all date fields to ensure standardized formatting."""
        for attr in ['created_at', 'updated_at', 'deleted_at']:
            if image.get(attr) is not None:
                image[attr] = image[attr].strftime('%Y-%m-%dT%H:%M:%SZ')

    def _format_status(self, image):
        """Update the status field to standardize format."""

        if 'status' not in image:
            return

        status_mapping = {
            'active': 'ACTIVE',
            'queued': 'SAVING',
            'saving': 'SAVING',
            'deleted': 'DELETED',
            'pending_delete': 'DELETED',
            'killed': 'ERROR',
        }

        try:
            image['status'] = status_mapping[image['status']]
        except KeyError:
            image['status'] = 'UNKNOWN'

    def _get_progress_for_status(self, status):
        progress_map = {
            'queued': 25,
            'saving': 50,
            'active': 100,
        }
        return progress_map.get(status, 0)

    def _build_server(self, image, image_obj):
        """Indicates that you must use a ViewBuilder subclass."""
        raise NotImplementedError()

    def generate_href(self, image_id):
        """Return an href string pointing to this object."""
        return os.path.join(self.base_url, "images", str(image_id))

    def build_list(self, image_objs, detail=False, **kwargs):
        """Return a standardized image list structure for display."""
        images = []
        for image_obj in image_objs:
            image = self.build(image_obj, detail=detail)
            images.append(image)

        return dict(images=images)

    def build(self, image_obj, detail=False):
        """Return a standardized image structure for display by the API."""
        self._format_dates(image_obj)

        orig_status = image_obj.get('status', '').lower()
        self._format_status(image_obj)

        image = {
            "id": image_obj.get("id"),
            "name": image_obj.get("name"),
        }

        self._build_server(image, image_obj)
        self._build_image_id(image, image_obj)

        if detail:
            image.update({
                "created": image_obj.get("created_at"),
                "updated": image_obj.get("updated_at"),
                "status": image_obj.get("status"),
            })
            image["progress"] = self._get_progress_for_status(orig_status)

        return image


class ViewBuilderV10(ViewBuilder):
    """OpenStack API v1.0 Image Builder"""

    def _build_server(self, image, image_obj):
        try:
            image['serverId'] = int(image_obj['properties']['instance_id'])
        except (KeyError, ValueError):
            pass

    def _build_image_id(self, image, image_obj):
        try:
            image['id'] = int(image_obj['id'])
        except ValueError:
            pass


class ViewBuilderV11(ViewBuilder):
    """OpenStack API v1.1 Image Builder"""

    def _build_server(self, image, image_obj):
        try:
            serverRef = image_obj['properties']['instance_ref']
            image['server'] = {
                "id": common.get_id_from_href(serverRef),
                "links": [
                    {
                        "rel": "self",
                        "href": serverRef,
                    },
                    {
                        "rel": "bookmark",
                        "href": common.remove_version_from_href(serverRef),
                    },
                ]
            }
        except KeyError:
            return

    def _build_image_id(self, image, image_obj):
        image['id'] = "%s" % image_obj['id']

    def generate_href(self, image_id):
        """Return an href string pointing to this object."""
        return os.path.join(self.base_url, self.project_id,
                            "images", str(image_id))

    def generate_next_link(self, image_id, params):
        """ Return an href string with proper limit and marker params"""
        params['marker'] = image_id
        return "%s?%s" % (
            os.path.join(self.base_url, self.project_id, "images"),
            common.dict_to_query_str(params))

    def build_list(self, image_objs, detail=False, **kwargs):
        """Return a standardized image list structure for display."""
        limit = kwargs.get('limit', None)
        images = []
        images_links = []

        for image_obj in image_objs:
            image = self.build(image_obj, detail=detail)
            images.append(image)

        if (len(images) and limit) and (limit == len(images)):
            next_link = self.generate_next_link(images[-1]["id"], kwargs)
            images_links = [dict(rel="next", href=next_link)]

        reval = dict(images=images)
        if len(images_links) > 0:
            reval['images_links'] = images_links

        return reval

    def build(self, image_obj, detail=False):
        """Return a standardized image structure for display by the API."""
        image = ViewBuilder.build(self, image_obj, detail)
        href = self.generate_href(image_obj["id"])
        bookmark = self.generate_bookmark(image_obj["id"])
        alternate = self.generate_alternate(image_obj["id"])

        image["links"] = [
            {
                "rel": "self",
                "href": href,
            },
            {
                "rel": "bookmark",
                "href": bookmark,
            },
            {
                "rel": "alternate",
                "type": "application/vnd.openstack.image",
                "href": alternate,
            },

        ]

        if detail:
            image["metadata"] = image_obj.get("properties", {})

            min_ram = image_obj.get('min_ram') or 0
            try:
                min_ram = int(min_ram)
            except ValueError:
                min_ram = 0
            image['minRam'] = min_ram

            min_disk = image_obj.get('min_disk') or 0
            try:
                min_disk = int(min_disk)
            except ValueError:
                min_disk = 0
            image['minDisk'] = min_disk

        return image

    def generate_bookmark(self, image_id):
        """Create a URL that refers to a specific flavor id."""
        return os.path.join(common.remove_version_from_href(self.base_url),
            self.project_id, "images", str(image_id))

    def generate_alternate(self, image_id):
        """Create an alternate link for a specific flavor id."""
        glance_url = utils.generate_glance_url()

        return "%s/%s/images/%s" % (glance_url, self.project_id,
                str(image_id))
