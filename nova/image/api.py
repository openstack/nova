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
from nova import profiler


@profiler.trace_cls("nova_image")
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

        :param _context: The `nova.context.Context` object for the request
        """
        # TODO(jaypipes): Refactor glance.get_remote_image_service and
        #                 glance.get_default_image_service into a single
        #                 method that takes a context and actually respects
        #                 it, returning a real session object that keeps
        #                 the context alive...
        return glance.get_default_image_service()

    @staticmethod
    def generate_image_url(image_ref, context):
        """Generate an image URL from an image_ref.

        :param image_ref: The image ref to generate URL
        :param context: The `nova.context.Context` object for the request
        """
        return "%s/images/%s" % (next(glance.get_api_servers(context)),
                                 image_ref)

    def get_all(self, context, **kwargs):
        """Retrieves all information records about all disk images available
        to show to the requesting user. If the requesting user is an admin,
        all images in an ACTIVE status are returned. If the requesting user
        is not an admin, the all public images and all private images that
        are owned by the requesting user in the ACTIVE status are returned.

        :param context: The `nova.context.Context` object for the request
        :param kwargs: A dictionary of filter and pagination values that
                       may be passed to the underlying image info driver.
        """
        session = self._get_session(context)
        return session.detail(context, **kwargs)

    def get(self, context, id_or_uri, include_locations=False,
            show_deleted=True):
        """Retrieves the information record for a single disk image. If the
        supplied identifier parameter is a UUID, the default driver will
        be used to return information about the image. If the supplied
        identifier is a URI, then the driver that matches that URI endpoint
        will be used to query for image information.

        :param context: The `nova.context.Context` object for the request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        :param include_locations: (Optional) include locations in the returned
                                  dict of information if the image service API
                                  supports it. If the image service API does
                                  not support the locations attribute, it will
                                  still be included in the returned dict, as an
                                  empty list.
        :param show_deleted: (Optional) show the image even the status of
                             image is deleted.
        """
        session, image_id = self._get_session_and_image_id(context, id_or_uri)
        return session.show(context, image_id,
                            include_locations=include_locations,
                            show_deleted=show_deleted)

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
        :param purge_props: Optional, defaults to False. If set, the backend
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

    def download(self, context, id_or_uri, data=None, dest_path=None):
        """Transfer image bits from Glance or a known source location to the
        supplied destination filepath.

        :param context: The `nova.context.RequestContext` object for the
                        request
        :param id_or_uri: A UUID identifier or an image URI to look up image
                          information for.
        :param data: A file object to use in downloading image data.
        :param dest_path: Filepath to transfer image bits to.

        Note that because of the poor design of the
        `glance.ImageService.download` method, the function returns different
        things depending on what arguments are passed to it. If a data argument
        is supplied but no dest_path is specified (only done in the XenAPI virt
        driver's image.utils module) then None is returned from the method. If
        the data argument is not specified but a destination path *is*
        specified, then a writeable file handle to the destination path is
        constructed in the method and the image bits written to that file, and
        again, None is returned from the method. If no data argument is
        supplied and no dest_path argument is supplied (VMWare and XenAPI virt
        drivers), then the method returns an iterator to the image bits that
        the caller uses to write to wherever location it wants. Finally, if the
        allow_direct_url_schemes CONF option is set to something, then the
        nova.image.download modules are used to attempt to do an SCP copy of
        the image bits from a file location to the dest_path and None is
        returned after retrying one or more download locations (libvirt and
        Hyper-V virt drivers through nova.virt.images.fetch).

        I think the above points to just how hacky/wacky all of this code is,
        and the reason it needs to be cleaned up and standardized across the
        virt driver callers.
        """
        # TODO(jaypipes): Deprecate and remove this method entirely when we
        #                 move to a system that simply returns a file handle
        #                 to a bytestream iterator and allows the caller to
        #                 handle streaming/copying/zero-copy as they see fit.
        session, image_id = self._get_session_and_image_id(context, id_or_uri)
        return session.download(context, image_id, data=data,
                                dst_path=dest_path)
