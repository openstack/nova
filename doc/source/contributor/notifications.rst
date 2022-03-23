=============
Notifications
=============

As discussed in :doc:`/admin/notifications`, nova emits notifications to the
message bus. There are two types of notifications provided in nova: legacy
(unversioned) notifications and versioned notifications. As a developer, you
may choose to add additional notifications or extend existing notifications.

.. note::

   This section provides information on adding your own notifications in nova.
   For background information on notifications including usage information,
   refer to :doc:`/admin/notifications`.
   For a list of available versioned notifications, refer to
   :doc:`/reference/notifications`.


How to add a new versioned notification
---------------------------------------

To provide the versioning for versioned notifications, each notification
is modeled with oslo.versionedobjects. Every versioned notification class
shall inherit from the ``nova.notifications.objects.base.NotificationBase``
which already defines three mandatory fields of the notification
``event_type``, ``publisher`` and ``priority``. The new notification class
shall add a new field ``payload`` with an appropriate payload type. The payload
object of the notifications shall inherit from the
``nova.notifications.objects.base.NotificationPayloadBase`` class and shall
define the fields of the payload as versionedobject fields. The base classes
are described in the following section.

.. rubric:: The ``nova.notifications.objects.base`` module

.. automodule:: nova.notifications.objects.base
    :noindex:
    :members:
    :show-inheritance:

Note that the notification objects must not be registered to the
``NovaObjectRegistry`` to avoid mixing nova-internal objects with the
notification objects. Instead, use the ``register_notification`` decorator on
every concrete notification object.

The following code example defines the necessary model classes for a new
notification ``myobject.update``.

.. code-block:: python

    @notification.notification_sample('myobject-update.json')
    @object_base.NovaObjectRegistry.register.register_notification
    class MyObjectNotification(notification.NotificationBase):
        # Version 1.0: Initial version
        VERSION = '1.0'

        fields = {
            'payload': fields.ObjectField('MyObjectUpdatePayload')
        }


    @object_base.NovaObjectRegistry.register.register_notification
    class MyObjectUpdatePayload(notification.NotificationPayloadBase):
        # Version 1.0: Initial version
        VERSION = '1.0'
        fields = {
            'some_data': fields.StringField(),
            'another_data': fields.StringField(),
        }


After that the notification can be populated and emitted with the following
code.

.. code-block:: python

    payload = MyObjectUpdatePayload(some_data="foo", another_data="bar")
    MyObjectNotification(
        publisher=notification.NotificationPublisher.from_service_obj(
            <nova.objects.service.Service instance that emits the notification>),
        event_type=notification.EventType(
            object='myobject',
            action=fields.NotificationAction.UPDATE),
        priority=fields.NotificationPriority.INFO,
        payload=payload).emit(context)

The above code will generate the following notification on the wire.

.. code-block:: json

    {
        "priority":"INFO",
        "payload":{
            "nova_object.namespace":"nova",
            "nova_object.name":"MyObjectUpdatePayload",
            "nova_object.version":"1.0",
            "nova_object.data":{
                "some_data":"foo",
                "another_data":"bar",
            }
        },
        "event_type":"myobject.update",
        "publisher_id":"<the name of the service>:<the host where the service runs>"
    }


There is a possibility to reuse an existing versionedobject as notification
payload by adding a ``SCHEMA`` field for the payload class that defines a
mapping between the fields of existing objects and the fields of the new
payload object. For example the service.status notification reuses the existing
``nova.objects.service.Service`` object when defines the notification's
payload.

.. code-block:: python

    @notification.notification_sample('service-update.json')
    @object_base.NovaObjectRegistry.register.register_notification
    class ServiceStatusNotification(notification.NotificationBase):
        # Version 1.0: Initial version
        VERSION = '1.0'

        fields = {
            'payload': fields.ObjectField('ServiceStatusPayload')
        }

    @object_base.NovaObjectRegistry.register.register_notification
    class ServiceStatusPayload(notification.NotificationPayloadBase):
        SCHEMA = {
            'host': ('service', 'host'),
            'binary': ('service', 'binary'),
            'topic': ('service', 'topic'),
            'report_count': ('service', 'report_count'),
            'disabled': ('service', 'disabled'),
            'disabled_reason': ('service', 'disabled_reason'),
            'availability_zone': ('service', 'availability_zone'),
            'last_seen_up': ('service', 'last_seen_up'),
            'forced_down': ('service', 'forced_down'),
            'version': ('service', 'version')
        }
        # Version 1.0: Initial version
        VERSION = '1.0'
        fields = {
            'host': fields.StringField(nullable=True),
            'binary': fields.StringField(nullable=True),
            'topic': fields.StringField(nullable=True),
            'report_count': fields.IntegerField(),
            'disabled': fields.BooleanField(),
            'disabled_reason': fields.StringField(nullable=True),
            'availability_zone': fields.StringField(nullable=True),
            'last_seen_up': fields.DateTimeField(nullable=True),
            'forced_down': fields.BooleanField(),
            'version': fields.IntegerField(),
        }

        def populate_schema(self, service):
            super(ServiceStatusPayload, self).populate_schema(service=service)

If the ``SCHEMA`` field is defined then the payload object needs to be
populated with the ``populate_schema`` call before it can be emitted.

.. code-block:: python

    payload = ServiceStatusPayload()
    payload.populate_schema(service=<nova.object.service.Service object>)
    ServiceStatusNotification(
        publisher=notification.NotificationPublisher.from_service_obj(
            <nova.object.service.Service object>),
        event_type=notification.EventType(
            object='service',
            action=fields.NotificationAction.UPDATE),
        priority=fields.NotificationPriority.INFO,
        payload=payload).emit(context)

The above code will emit the :ref:`already shown notification <service.update>`
on the wire.

Every item in the ``SCHEMA`` has the syntax of::

    <payload field name which needs to be filled>:
        (<name of the parameter of the populate_schema call>,
         <the name of a field of the parameter object>)

The mapping defined in the ``SCHEMA`` field has the following semantics. When
the ``populate_schema`` function is called the content of the ``SCHEMA`` field
is enumerated and the value of the field of the pointed parameter object is
copied to the requested payload field. So in the above example the ``host``
field of the payload object is populated from the value of the ``host`` field
of the ``service`` object that is passed as a parameter to the
``populate_schema`` call.

A notification payload object can reuse fields from multiple existing
objects. Also a notification can have both new and reused fields in its
payload.

Note that the notification's publisher instance can be created two different
ways. It can be created by instantiating the ``NotificationPublisher`` object
with a ``host`` and a ``source`` string parameter or it can be generated from a
``Service`` object by calling ``NotificationPublisher.from_service_obj``
function.

Versioned notifications shall have a sample file stored under
``doc/sample_notifications`` directory and the notification object shall be
decorated with the ``notification_sample`` decorator. For example the
``service.update`` notification has a sample file stored in
``doc/sample_notifications/service-update.json`` and the
``ServiceUpdateNotification`` class is decorated accordingly.

Notification payload classes can use inheritance to avoid duplicating common
payload fragments in nova code. However the leaf classes used directly in a
notification should be created with care to avoid future needs of adding extra
level of inheritance that changes the name of the leaf class as that name is
present in the payload class. If this cannot be avoided and the only change is
the renaming then the version of the new payload shall be the same as the old
payload was before the rename. See [1]_ as an example. If the renaming
involves any other changes on the payload (e.g. adding new fields) then the
version of the new payload shall be higher than the old payload was. See [2]_
as an example.


What should be in the notification payload?
-------------------------------------------

This is just a guideline. You should always consider the actual use case that
requires the notification.

* Always include the identifier (e.g. uuid) of the entity that can be used to
  query the whole entity over the REST API so that the consumer can get more
  information about the entity.

* You should consider including those fields that are related to the event
  you are sending the notification about. For example if a change of a field of
  the entity triggers an update notification then you should include the field
  to the payload.

* An update notification should contain information about what part of the
  entity is changed. Either by filling the nova_object.changes part of the
  payload (note that it is not supported by the notification framework
  currently) or sending both the old state and the new state of the entity in
  the payload.

* You should never include a nova internal object in the payload. Create a new
  object and use the SCHEMA field to map the internal object to the
  notification payload. This way the evolution of the internal object model
  can be decoupled from the evolution of the notification payload.

  .. important::

      This does not mean that every field from internal objects
      should be mirrored in the notification payload objects.
      Think about what is actually needed by a consumer before
      adding it to a payload. When in doubt, if no one is requesting
      specific information in notifications, then leave it out until
      someone asks for it.

* The delete notification should contain the same information as the create or
  update notifications. This makes it possible for the consumer to listen only to
  the delete notifications but still filter on some fields of the entity
  (e.g. project_id).


What should **NOT** be in the notification payload
--------------------------------------------------

* Generally anything that contains sensitive information about the internals
  of the nova deployment, for example fields that contain access credentials
  to a cell database or message queue (see `bug 1823104`_).

.. _bug 1823104: https://bugs.launchpad.net/nova/+bug/1823104

.. references:

.. [1] https://review.opendev.org/#/c/463001/
.. [2] https://review.opendev.org/#/c/453077/
