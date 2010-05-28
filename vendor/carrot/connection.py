"""

Getting a connection to the AMQP server.

"""
from amqplib.client_0_8.connection import AMQPConnectionException
from carrot.backends import get_backend_cls
import warnings
import socket

DEFAULT_CONNECT_TIMEOUT = 5 # seconds
SETTING_PREFIX = "BROKER"
COMPAT_SETTING_PREFIX = "AMQP"
ARG_TO_DJANGO_SETTING = {
        "hostname": "HOST",
        "userid": "USER",
        "password": "PASSWORD",
        "virtual_host": "VHOST",
        "port": "PORT",
}
SETTING_DEPRECATED_FMT = "Setting %s has been renamed to %s and is " \
                         "scheduled for removal in version 1.0."


class BrokerConnection(object):
    """A network/socket connection to an AMQP message broker.

    :param hostname: see :attr:`hostname`.
    :param userid: see :attr:`userid`.
    :param password: see :attr:`password`.

    :keyword virtual_host: see :attr:`virtual_host`.
    :keyword port: see :attr:`port`.
    :keyword insist: see :attr:`insist`.
    :keyword connect_timeout: see :attr:`connect_timeout`.
    :keyword ssl: see :attr:`ssl`.

    .. attribute:: hostname

        The hostname to the AMQP server

    .. attribute:: userid

        A valid username used to authenticate to the server.

    .. attribute:: password

        The password used to authenticate to the server.

    .. attribute:: virtual_host

        The name of the virtual host to work with. This virtual host must
        exist on the server, and the user must have access to it. Consult
        your brokers manual for help with creating, and mapping
        users to virtual hosts.
        Default is ``"/"``.

    .. attribute:: port

        The port of the AMQP server.  Default is ``5672`` (amqp).

    .. attribute:: insist

        Insist on connecting to a server. In a configuration with multiple
        load-sharing servers, the insist option tells the server that the
        client is insisting on a connection to the specified server.
        Default is ``False``.

    .. attribute:: connect_timeout

        The timeout in seconds before we give up connecting to the server.
        The default is no timeout.

    .. attribute:: ssl

        Use SSL to connect to the server.
        The default is ``False``.

    .. attribute:: backend_cls

        The messaging backend class used. Defaults to the ``pyamqplib``
        backend.

    """
    virtual_host = "/"
    port = None
    insist = False
    connect_timeout = DEFAULT_CONNECT_TIMEOUT
    ssl = False
    _closed = True
    backend_cls = None

    ConnectionException = AMQPConnectionException

    @property
    def host(self):
        """The host as a hostname/port pair separated by colon."""
        return ":".join([self.hostname, str(self.port)])

    def __init__(self, hostname=None, userid=None, password=None,
            virtual_host=None, port=None, **kwargs):
        self.hostname = hostname
        self.userid = userid
        self.password = password
        self.virtual_host = virtual_host or self.virtual_host
        self.port = port or self.port
        self.insist = kwargs.get("insist", self.insist)
        self.connect_timeout = kwargs.get("connect_timeout",
                                          self.connect_timeout)
        self.ssl = kwargs.get("ssl", self.ssl)
        self.backend_cls = kwargs.get("backend_cls", None)
        self._closed = None
        self._connection = None

    @property
    def connection(self):
        if self._closed == True:
            return
        if not self._connection:
            self._connection = self._establish_connection()
            self._closed = False
        return self._connection

    def __enter__(self):
        return self

    def __exit__(self, e_type, e_value, e_trace):
        if e_type:
            raise e_type(e_value)
        self.close()

    def _establish_connection(self):
        return self.create_backend().establish_connection()

    def get_backend_cls(self):
        """Get the currently used backend class."""
        backend_cls = self.backend_cls
        if not backend_cls or isinstance(backend_cls, basestring):
            backend_cls = get_backend_cls(backend_cls)
        return backend_cls

    def create_backend(self):
        """Create a new instance of the current backend in
        :attr:`backend_cls`."""
        backend_cls = self.get_backend_cls()
        return backend_cls(connection=self)

    def get_channel(self):
        """Request a new AMQP channel."""
        return self.connection.channel()

    def connect(self):
        """Establish a connection to the AMQP server."""
        self._closed = False
        return self.connection

    def close(self):
        """Close the currently open connection."""
        try:
            if self._connection:
                backend = self.create_backend()
                backend.close_connection(self._connection)
        except socket.error:
            pass
        self._closed = True

# For backwards compatability.
AMQPConnection = BrokerConnection


def get_django_conninfo():
    # FIXME can't wait to remove this mess in 1.0 [askh]
    ci = {}
    from django.conf import settings as django_settings

    ci["backend_cls"] = getattr(django_settings, "CARROT_BACKEND", None)

    for arg_name, setting_name in ARG_TO_DJANGO_SETTING.items():
        setting = "%s_%s" % (SETTING_PREFIX, setting_name)
        compat_setting = "%s_%s" % (COMPAT_SETTING_PREFIX, setting_name)
        if hasattr(django_settings, setting):
            ci[arg_name] = getattr(django_settings, setting, None)
        elif hasattr(django_settings, compat_setting):
            ci[arg_name] = getattr(django_settings, compat_setting, None)
            warnings.warn(DeprecationWarning(SETTING_DEPRECATED_FMT % (
                compat_setting, setting)))

    if "hostname" not in ci:
        if hasattr(django_settings, "AMQP_SERVER"):
            ci["hostname"] = django_settings.AMQP_SERVER
            warnings.warn(DeprecationWarning(
                "AMQP_SERVER has been renamed to BROKER_HOST and is"
                "scheduled for removal in version 1.0."))

    return ci


class DjangoBrokerConnection(BrokerConnection):
    """A version of :class:`BrokerConnection` that takes configuration
    from the Django ``settings.py`` module.

    :keyword hostname: The hostname of the AMQP server to connect to,
        if not provided this is taken from ``settings.BROKER_HOST``.

    :keyword userid: The username of the user to authenticate to the server
        as. If not provided this is taken from ``settings.BROKER_USER``.

    :keyword password: The users password. If not provided this is taken
        from ``settings.BROKER_PASSWORD``.

    :keyword virtual_host: The name of the virtual host to work with.
        This virtual host must exist on the server, and the user must
        have access to it. Consult your brokers manual for help with
        creating, and mapping users to virtual hosts. If not provided
        this is taken from ``settings.BROKER_VHOST``.

    :keyword port: The port the AMQP server is running on. If not provided
        this is taken from ``settings.BROKER_PORT``, or if that is not set,
        the default is ``5672`` (amqp).

    """


    def __init__(self, *args, **kwargs):
        kwargs = dict(get_django_conninfo(), **kwargs)
        super(DjangoBrokerConnection, self).__init__(*args, **kwargs)

# For backwards compatability.
DjangoAMQPConnection = DjangoBrokerConnection
