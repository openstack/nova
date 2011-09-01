from nova import exception
from nova import flags
from nova import log as logging

LOG = logging.getLogger('nova.rpc')

flags.DEFINE_integer('rpc_thread_pool_size', 1024,
                             'Size of RPC thread pool')
flags.DEFINE_integer('rpc_conn_pool_size', 30,
                             'Size of RPC connection pool')


class RemoteError(exception.Error):
    """Signifies that a remote class has raised an exception.

    Containes a string representation of the type of the original exception,
    the value of the original exception, and the traceback.  These are
    sent to the parent as a joined string so printing the exception
    contains all of the relevent info.

    """

    def __init__(self, exc_type, value, traceback):
        self.exc_type = exc_type
        self.value = value
        self.traceback = traceback
        super(RemoteError, self).__init__('%s %s\n%s' % (exc_type,
                                                         value,
                                                         traceback))
