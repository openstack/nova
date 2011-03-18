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


class Builder(object):
    """
    Base class for generating responses to OpenStack API requests for
    information about images.
    """

    def build(self, request, image_obj, detail=False):
        """
        Return a standardized image structure for display by the API.
        """
        image = {
            "id": image_obj["id"],
            "name": image_obj["name"],
        }

        if detail:
            image.update({
                "created": image_obj["created_at"],
                "updated": image_obj["updated_at"],
                "status": image_obj["status"],
            })

        return image


class Builder_v1_0(Builder):
    pass


class Builder_v1_1(Builder):
    """
    OpenStack API v1.1 Image Builder
    """

    def build(self, request, image_obj, detail=False):
        """
        Return a standardized image structure for display by the API.
        """
        image = Builder.build(self, request, image_obj, detail)
        href = "%s/images/%s" % (request.application_url, image_obj["id"])

        image["links"] = [{
            "rel": "self",
            "href": href,
        },
        {
            "rel": "bookmark",
            "type": "application/json",
            "href": href,
        },
        {
            "rel": "bookmark",
            "type": "application/xml",
            "href": href,
        }]

        return image
