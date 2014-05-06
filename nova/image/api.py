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

"""
Main abstraction layer for retrieving and storing information about disk
images used by the compute layer.
"""

from nova.image import glance


class API(object):

    """Responsible for exposing a relatively stable internal API for other
    modules in Nova to retrieve information about disk images. This API
    attempts to match the nova.volume.api and nova.network.api calling
    interface.
    """

    def _get_session_and_image_id(self, context, id_or_uri):
        """Returns a tuple of (session, image_id). If the supplied `id_or_uri`
        is an image ID, then the default client session will be returned
        for the context's user, along with the image ID. If the supplied
        `id_or_uri` parameter is a URI, then a client session connecting to
        the URI's image service endpoint will be returned along with a
        parsed image ID from that URI.

        :param context: The `nova.context.Context` object for the request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        """
        return glance.get_remote_image_service(context, id_or_uri)

    def _get_session(self, _context):
        """Returns a client session that can be used to query for image
        information.

        :param context: The `nova.context.Context` object for the request
        """
        #TODO(jaypipes): Refactor glance.get_remote_image_service and
        #                glance.get_default_image_service into a single
        #                method that takes a context and actually respects
        #                it, returning a real session object that keeps
        #                the context alive...
        return glance.get_default_image_service()

    def get_all(self, context, **kwargs):
        """Retrieves all information records about all disk images available
        to show to the requesting user. If the requesting user is an admin,
        all images in an ACTIVE status are returned. If the requesting user
        is not an admin, the all public images and all private images that
        are owned by the requesting user in the ACTIVE status are returned.

        :param context: The `nova.context.Context` object for the request
        :param **kwargs: A dictionary of filter and pagination values that
                         may be passed to the underlying image info driver.
        """
        session = self._get_session(context)
        return session.detail(context, **kwargs)

    def get(self, context, id_or_uri):
        """Retrieves the information record for a single disk image. If the
        supplied identifier parameter is a UUID, the default driver will
        be used to return information about the image. If the supplied
        identifier is a URI, then the driver that matches that URI endpoint
        will be used to query for image information.

        :param context: The `nova.context.Context` object for the request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        """
        session, image_id = self._get_session_and_image_id(context, id_or_uri)
        return session.show(context, image_id)

    def create(self, context, image_info, data=None):
        """Creates a new image record, optionally passing the image bits to
        backend storage.

        :param context: The `nova.context.Context` object for the request
        :param image_info: A dict of information about the image that is
                           passed to the image registry.
        :param data: Optional file handle or bytestream iterator that is
                     passed to backend storage.
        """
        session = self._get_session(context)
        return session.create(context, image_info, data=data)

    def update(self, context, id_or_uri, image_info,
               data=None, purge_props=False):
        """Update the information about an image, optionally along with a file
        handle or bytestream iterator for image bits. If the optional file
        handle for updated image bits is supplied, the image may not have
        already uploaded bits for the image.

        :param context: The `nova.context.Context` object for the request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        :param image_info: A dict of information about the image that is
                           passed to the image registry.
        :param data: Optional file handle or bytestream iterator that is
                     passed to backend storage.
        :param purge_props: Optional, defaults to True. If set, the backend
                            image registry will clear all image properties
                            and replace them the image properties supplied
                            in the image_info dictionary's 'properties'
                            collection.
        """
        session, image_id = self._get_session_and_image_id(context, id_or_uri)
        return session.update(context, image_id, image_info, data=data,
                              purge_props=purge_props)

    def delete(self, context, id_or_uri):
        """Delete the information about an image and mark the image bits for
        deletion.

        :param context: The `nova.context.Context` object for the request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        """
        session, image_id = self._get_session_and_image_id(context, id_or_uri)
        return session.delete(context, image_id)
