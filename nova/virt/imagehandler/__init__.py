# Copyright 2014 IBM Corp.
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

"""
Handling of VM disk images by handler.
"""

import urlparse

from oslo.config import cfg
import stevedore

from nova import exception
from nova.image import glance
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

image_opts = [
    cfg.ListOpt('image_handlers',
                default=['download'],
                help='Specifies which image handler extension names to use '
                     'for handling images. The first extension in the list '
                     'which can handle the image with a suitable location '
                     'will be used.'),
]

CONF = cfg.CONF
CONF.register_opts(image_opts)

_IMAGE_HANDLERS = []
_IMAGE_HANDLERS_ASSO = {}


def _image_handler_asso(handler, path, location, image_meta):
    _IMAGE_HANDLERS_ASSO[path] = (handler, location, image_meta)


def _image_handler_disasso(handler, path):
    _IMAGE_HANDLERS_ASSO.pop(path, None)


def _match_locations(locations, schemes):
    matched = []
    if locations and (schemes is not None):
        for loc in locations:
            # Note(zhiyan): location = {'url': 'string',
            #                           'metadata': {...}}
            if len(schemes) == 0:
                # Note(zhiyan): handler has not scheme limitation.
                matched.append(loc)
            elif urlparse.urlparse(loc['url']).scheme in schemes:
                matched.append(loc)
    return matched


def load_image_handlers(driver):
    """Loading construct user configured image handlers.

    Handler objects will be cached to keep handler instance as singleton
    since this structure need support follow sub-class development,
    developer could implement particular sub-class in relevant hypervisor
    layer with more advanced functions.
    The handler's __init__() need do some re-preparing work if it needed,
    for example when nova-compute service restart or host reboot,
    CinderImageHandler will need to re-preapre iscsi/fc link for volumes
    those already be cached on compute host as template image previously.
    """
    global _IMAGE_HANDLERS, _IMAGE_HANDLERS_ASSO
    if _IMAGE_HANDLERS:
        _IMAGE_HANDLERS = []
        _IMAGE_HANDLERS_ASSO = {}
    # for de-duplicate. using ordereddict lib to support both py26 and py27?
    processed_handler_names = []
    ex = stevedore.extension.ExtensionManager('nova.virt.image.handlers')
    for name in CONF.image_handlers:
        if not name:
            continue
        name = name.strip()
        if name in processed_handler_names:
            LOG.warn(_("Duplicated handler extension name in 'image_handlers' "
                       "option: %s, skip."), name)
            continue
        elif name not in ex.names():
            LOG.warn(_("Invalid handler extension name in 'image_handlers' "
                       "option: %s, skip."), name)
            continue
        processed_handler_names.append(name)
        try:
            mgr = stevedore.driver.DriverManager(
                namespace='nova.virt.image.handlers',
                name=name,
                invoke_on_load=True,
                invoke_kwds={"driver": driver,
                             "associate_fn": _image_handler_asso,
                             "disassociate_fn": _image_handler_disasso})
            _IMAGE_HANDLERS.append(mgr.driver)
        except Exception as err:
            LOG.warn(_("Failed to import image handler extension "
                       "%(name)s: %(err)s"), {'name': name, 'err': err})


def handle_image(context=None, image_id=None,
                 user_id=None, project_id=None,
                 target_path=None):
    """Handle image using available handles.

    This generator will return each available handler on each time.
    :param context: Request context
    :param image_id: The opaque image identifier
    :param user_id: Request user id
    :param project_id: Request project id
    :param target_path: Where the image data to write
    :raises NoImageHandlerAvailable: if no any image handler specified in
        the configuration is available for this request.
    """

    handled = False

    if target_path is not None:
        target_path = target_path.strip()

    # Check if target image has been handled before,
    # we can using previous handler process it again directly.
    if target_path and _IMAGE_HANDLERS_ASSO:
        ret = _IMAGE_HANDLERS_ASSO.get(target_path)
        if ret:
            (image_handler, location, image_meta) = ret
            yield image_handler, location, image_meta
            handled = image_handler.last_ops_handled()

    image_meta = None

    if not handled and _IMAGE_HANDLERS:
        if context and image_id:
            (image_service, _image_id) = glance.get_remote_image_service(
                                                            context, image_id)
            image_meta = image_service.show(context, image_id)
            # Note(zhiyan): Glance maybe can not receive image
            # location property since Glance disabled it by default.
            img_locs = image_service.get_locations(context, image_id)
            for image_handler in _IMAGE_HANDLERS:
                matched_locs = _match_locations(img_locs,
                                                image_handler.get_schemes())
                for loc in matched_locs:
                    yield image_handler, loc, image_meta
                    handled = image_handler.last_ops_handled()
                    if handled:
                        return

        if not handled:
            # Note(zhiyan): using location-independent handler do it.
            for image_handler in _IMAGE_HANDLERS:
                if len(image_handler.get_schemes()) == 0:
                    yield image_handler, None, image_meta
                    handled = image_handler.last_ops_handled()
                    if handled:
                        return

    if not handled:
        LOG.error(_("Can't handle image: %(image_id)s %(target_path)s"),
                  {'image_id': image_id, 'target_path': target_path})
        raise exception.NoImageHandlerAvailable(image_id=image_id)
