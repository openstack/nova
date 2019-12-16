#    Copyright 2018 NTT Corporation
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

from nova.notifications.objects import base
from nova.objects import base as nova_base
from nova.objects import fields
from nova.objects import image_meta


@nova_base.NovaObjectRegistry.register_notification
class ImageMetaPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'id': ('image_meta', 'id'),
        'name': ('image_meta', 'name'),
        'status': ('image_meta', 'status'),
        'visibility': ('image_meta', 'visibility'),
        'protected': ('image_meta', 'protected'),
        'checksum': ('image_meta', 'checksum'),
        'owner': ('image_meta', 'owner'),
        'size': ('image_meta', 'size'),
        'virtual_size': ('image_meta', 'virtual_size'),
        'container_format': ('image_meta', 'container_format'),
        'disk_format': ('image_meta', 'disk_format'),
        'created_at': ('image_meta', 'created_at'),
        'updated_at': ('image_meta', 'updated_at'),
        'tags': ('image_meta', 'tags'),
        'direct_url': ('image_meta', 'direct_url'),
        'min_ram': ('image_meta', 'min_ram'),
        'min_disk': ('image_meta', 'min_disk')
    }

    # NOTE(takashin): The reason that each field is nullable is as follows.
    #
    # a. It is defined as "The value might be null (JSON null data type)."
    #    in the "Show image" API (GET /v2/images/{image_id})
    #    in the glance API v2 Reference.
    #    (https://docs.openstack.org/api-ref/image/v2/index.html)
    #
    #   * checksum
    #   * container_format
    #   * disk_format
    #   * min_disk
    #   * min_ram
    #   * name
    #   * owner
    #   * size
    #   * updated_at
    #   * virtual_size
    #
    # b. It is optional in the response from glance.
    #   * direct_url
    #
    # a. It is defined as nullable in the ImageMeta object.
    #   * created_at
    #
    # c. It cannot be got in the boot from volume case.
    #    See VIM_IMAGE_ATTRIBUTES in nova/utils.py.
    #
    #   * id (not 'image_id')
    #   * visibility
    #   * protected
    #   * status
    #   * tags
    fields = {
        'id': fields.UUIDField(nullable=True),
        'name': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'visibility': fields.StringField(nullable=True),
        'protected': fields.FlexibleBooleanField(nullable=True),
        'checksum': fields.StringField(nullable=True),
        'owner': fields.StringField(nullable=True),
        'size': fields.IntegerField(nullable=True),
        'virtual_size': fields.IntegerField(nullable=True),
        'container_format': fields.StringField(nullable=True),
        'disk_format': fields.StringField(nullable=True),
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'tags': fields.ListOfStringsField(nullable=True),
        'direct_url': fields.StringField(nullable=True),
        'min_ram': fields.IntegerField(nullable=True),
        'min_disk': fields.IntegerField(nullable=True),
        'properties': fields.ObjectField('ImageMetaPropsPayload')
    }

    def __init__(self, image_meta):
        super(ImageMetaPayload, self).__init__()
        self.properties = ImageMetaPropsPayload(
            image_meta_props=image_meta.properties)
        self.populate_schema(image_meta=image_meta)


@nova_base.NovaObjectRegistry.register_notification
class ImageMetaPropsPayload(base.NotificationPayloadBase):
    """Built dynamically from ImageMetaProps.

    This has the following implications:

    * When you make a versioned update to ImageMetaProps, you must *also* bump
      the version of this object, even though you didn't make any explicit
      changes here. There's an object hash test that should catch this for you.
    * As currently written, this relies on all of the fields of ImageMetaProps
      being initialized with no arguments. If you add one with arguments (e.g.
      ``nullable=True`` or with a ``default``), something needs to change here.
    """
    # Version 1.0: Initial version
    # Version 1.1: Added 'gop', 'virtio' and  'none' to hw_video_model field
    # Version 1.2: Added hw_pci_numa_affinity_policy field
    # Version 1.3: Added hw_mem_encryption, hw_pmu and hw_time_hpet fields
    VERSION = '1.3'

    SCHEMA = {
        k: ('image_meta_props', k) for k in image_meta.ImageMetaProps.fields}

    # NOTE(efried): This logic currently relies on all of the fields of
    # ImageMetaProps being initialized with no arguments. See the docstring.
    # NOTE(efried): It's possible this could just be:
    #      fields = image_meta.ImageMetaProps.fields
    #  But it is not clear that OVO can tolerate the same *instance* of a type
    #  class being used in more than one place.
    fields = {
        k: v.__class__() for k, v in image_meta.ImageMetaProps.fields.items()}

    def __init__(self, image_meta_props):
        super(ImageMetaPropsPayload, self).__init__()
        # NOTE(takashin): If fields are not set in the ImageMetaProps object,
        # it will not set the fields in the ImageMetaPropsPayload
        # in order to avoid too many fields whose values are None.
        self.populate_schema(set_none=False, image_meta_props=image_meta_props)
