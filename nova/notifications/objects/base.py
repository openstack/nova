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


from nova.objects import base
from nova.objects import fields
from nova import rpc


@base.NovaObjectRegistry.register
class EventType(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'object': fields.StringField(nullable=False),
        'action': fields.NotificationActionField(nullable=False),
        'phase': fields.NotificationPhaseField(nullable=True),
    }

    def to_notification_event_type_field(self):
        """Serialize the object to the wire format."""
        s = '%s.%s' % (self.object, self.action)
        if self.obj_attr_is_set('phase'):
            s += '.%s' % self.phase
        return s


# Note(gibi): It is explicitly not registered as this class shall not be used
# directly, it is just a base class for notification payloads.
@base.NovaObjectRegistry.register_if(False)
class NotificationPayloadBase(base.NovaObject):
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

    def __init__(self, *args, **kwargs):
        super(NotificationPayloadBase, self).__init__(*args, **kwargs)
        self.populated = not self.SCHEMA

    def populate_schema(self, **kwargs):
        """Populate the object based on the SCHEMA and the source objects

        :param kwargs: A dict contains the source object at the key defined in
                       the SCHEMA
        """
        for key, (obj, field) in self.SCHEMA.items():
            source = kwargs[obj]
            if source.obj_attr_is_set(field):
                setattr(self, key, getattr(source, field))
        self.populated = True


@base.NovaObjectRegistry.register
class NotificationPublisher(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'host': fields.StringField(nullable=False),
        'binary': fields.StringField(nullable=False),
    }

    @classmethod
    def from_service_obj(cls, service):
        return cls(host=service.host, binary=service.binary)


# Note(gibi): It is explicitly not registered as this class shall not be used
# directly, it is just a base class for notification.
@base.NovaObjectRegistry.register_if(False)
class NotificationBase(base.NovaObject):
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

    def emit(self, context):
        """Send the notification."""
        assert self.payload.populated

        # Note(gibi): notification payload will be a newly populated object
        # therefore every field of it will look changed so this does not carry
        # any extra information so we drop this from the payload.
        self.payload.obj_reset_changes(recursive=False)

        self._emit(context,
                   event_type=
                   self.event_type.to_notification_event_type_field(),
                   publisher_id='%s:%s' %
                                (self.publisher.binary,
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
        cls.sample = sample
        return cls
    return wrap
