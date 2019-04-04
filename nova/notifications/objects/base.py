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
from oslo_log import log as logging
from oslo_utils import excutils
from oslo_versionedobjects import exception as ovo_exception

from nova import exception
from nova.objects import base
from nova.objects import fields
from nova import rpc

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register_if(False)
class NotificationObject(base.NovaObject):
    """Base class for every notification related versioned object."""
    # Version 1.0: Initial version
    VERSION = '1.0'

    def __init__(self, **kwargs):
        super(NotificationObject, self).__init__(**kwargs)
        # The notification objects are created on the fly when nova emits the
        # notification. This causes that every object shows every field as
        # changed. We don't want to send this meaningless information so we
        # reset the object after creation.
        self.obj_reset_changes(recursive=False)


@base.NovaObjectRegistry.register_notification
class EventType(NotificationObject):
    # Version 1.0: Initial version
    # Version 1.1: New valid actions values are added to the
    #              NotificationActionField enum
    # Version 1.2: DELETE value is added to the NotificationActionField enum
    # Version 1.3: Set of new values are added to NotificationActionField enum
    # Version 1.4: Another set of new values are added to
    #              NotificationActionField enum
    # Version 1.5: Aggregate related values have been added to
    #              NotificationActionField enum
    # Version 1.6: ADD_FIX_IP replaced with INTERFACE_ATTACH in
    #              NotificationActionField enum
    # Version 1.7: REMOVE_FIXED_IP replaced with INTERFACE_DETACH in
    #              NotificationActionField enum
    # Version 1.8: IMPORT value is added to NotificationActionField enum
    # Version 1.9: ADD_MEMBER value is added to NotificationActionField enum
    # Version 1.10: UPDATE_METADATA value is added to the
    #               NotificationActionField enum
    # Version 1.11: LOCK is added to NotificationActionField enum
    # Version 1.12: UNLOCK is added to NotificationActionField enum
    # Version 1.13: REBUILD_SCHEDULED value is added to the
    #               NotificationActionField enum
    # Version 1.14: UPDATE_PROP value is added to the NotificationActionField
    #               enum
    # Version 1.15: LIVE_MIGRATION_FORCE_COMPLETE is added to the
    #               NotificationActionField enum
    # Version 1.16: CONNECT is added to NotificationActionField enum
    # Version 1.17: USAGE is added to NotificationActionField enum
    # Version 1.18: ComputeTask related values have been added to
    #               NotificationActionField enum
    # Version 1.19: SELECT_DESTINATIONS is added to the NotificationActionField
    #               enum
    VERSION = '1.19'

    fields = {
        'object': fields.StringField(nullable=False),
        'action': fields.NotificationActionField(nullable=False),
        'phase': fields.NotificationPhaseField(nullable=True),
    }

    def __init__(self, object, action, phase=None):
        super(EventType, self).__init__()
        self.object = object
        self.action = action
        self.phase = phase

    def to_notification_event_type_field(self):
        """Serialize the object to the wire format."""
        s = '%s.%s' % (self.object, self.action)
        if self.phase:
            s += '.%s' % self.phase
        return s


@base.NovaObjectRegistry.register_if(False)
class NotificationPayloadBase(NotificationObject):
    """Base class for the payload of versioned notifications."""
    # SCHEMA defines how to populate the payload fields. It is a dictionary
    # where every key value pair has the following format:
    # <payload_field_name>: (<data_source_name>,
    #                        <field_of_the_data_source>)
    # The <payload_field_name> is the name where the data will be stored in the
    # payload object, this field has to be defined as a field of the payload.
    # The <data_source_name> shall refer to name of the parameter passed as
    # kwarg to the payload's populate_schema() call and this object will be
    # used as the source of the data. The <field_of_the_data_source> shall be
    # a valid field of the passed argument.
    # The SCHEMA needs to be applied with the populate_schema() call before the
    # notification can be emitted.
    # The value of the payload.<payload_field_name> field will be set by the
    # <data_source_name>.<field_of_the_data_source> field. The
    # <data_source_name> will not be part of the payload object internal or
    # external representation.
    # Payload fields that are not set by the SCHEMA can be filled in the same
    # way as in any versioned object.
    SCHEMA = {}
    # Version 1.0: Initial version
    VERSION = '1.0'

    def __init__(self):
        super(NotificationPayloadBase, self).__init__()
        self.populated = not self.SCHEMA

    @rpc.if_notifications_enabled
    def populate_schema(self, set_none=True, **kwargs):
        """Populate the object based on the SCHEMA and the source objects

        :param kwargs: A dict contains the source object at the key defined in
                       the SCHEMA
        """
        for key, (obj, field) in self.SCHEMA.items():
            source = kwargs[obj]
            # trigger lazy-load if possible
            try:
                setattr(self, key, getattr(source, field))
            # ObjectActionError - not lazy loadable field
            # NotImplementedError - obj_load_attr() is not even defined
            # OrphanedObjectError - lazy loadable field but context is None
            except (exception.ObjectActionError,
                    NotImplementedError,
                    exception.OrphanedObjectError,
                    ovo_exception.OrphanedObjectError):
                if set_none:
                    # If it is unset or non lazy loadable in the source object
                    # then we cannot do anything else but try to default it
                    # in the payload object we are generating here.
                    # NOTE(gibi): This will fail if the payload field is not
                    # nullable, but that means that either the source object
                    # is not properly initialized or the payload field needs
                    # to be defined as nullable
                    setattr(self, key, None)
            except Exception:
                with excutils.save_and_reraise_exception():
                    LOG.error('Failed trying to populate attribute "%s" '
                              'using field: %s', key, field)

        self.populated = True

        # the schema population will create changed fields but we don't need
        # this information in the notification
        self.obj_reset_changes(recursive=True)


@base.NovaObjectRegistry.register_notification
class NotificationPublisher(NotificationObject):
    # Version 1.0: Initial version
    #         2.0: The binary field has been renamed to source
    #         2.1: The type of the source field changed from string to enum.
    #              This only needs a minor bump as the enum uses the possible
    #              values of the previous string field
    #         2.2: New enum for source fields added
    VERSION = '2.2'

    # TODO(stephenfin): Remove 'nova-cells' from 'NotificationSourceField' enum
    # when bumping this object to version 3.0
    fields = {
        'host': fields.StringField(nullable=False),
        'source': fields.NotificationSourceField(nullable=False),
    }

    def __init__(self, host, source):
        super(NotificationPublisher, self).__init__()
        self.host = host
        self.source = source

    @classmethod
    def from_service_obj(cls, service):
        source = fields.NotificationSource.get_source_by_binary(service.binary)
        return cls(host=service.host, source=source)


@base.NovaObjectRegistry.register_if(False)
class NotificationBase(NotificationObject):
    """Base class for versioned notifications.

    Every subclass shall define a 'payload' field.
    """
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'priority': fields.NotificationPriorityField(),
        'event_type': fields.ObjectField('EventType'),
        'publisher': fields.ObjectField('NotificationPublisher'),
    }

    def _emit(self, context, event_type, publisher_id, payload):
        notifier = rpc.get_versioned_notifier(publisher_id)
        notify = getattr(notifier, self.priority)
        notify(context, event_type=event_type, payload=payload)

    @rpc.if_notifications_enabled
    def emit(self, context):
        """Send the notification."""
        assert self.payload.populated

        # Note(gibi): notification payload will be a newly populated object
        # therefore every field of it will look changed so this does not carry
        # any extra information so we drop this from the payload.
        self.payload.obj_reset_changes(recursive=True)

        self._emit(context,
                   event_type=
                   self.event_type.to_notification_event_type_field(),
                   publisher_id='%s:%s' %
                                (self.publisher.source,
                                 self.publisher.host),
                   payload=self.payload.obj_to_primitive())


def notification_sample(sample):
    """Class decorator to attach the notification sample information
    to the notification object for documentation generation purposes.

    :param sample: the path of the sample json file relative to the
                   doc/notification_samples/ directory in the nova repository
                   root.
    """
    def wrap(cls):
        if not getattr(cls, 'samples', None):
            cls.samples = [sample]
        else:
            cls.samples.append(sample)
        return cls
    return wrap
