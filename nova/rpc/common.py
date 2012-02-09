import copy

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


def _safe_log(log_func, msg, msg_data):
    """Sanitizes the msg_data field before logging."""
    SANITIZE = {
                'set_admin_password': ('new_pass',),
                'run_instance': ('admin_password',),
               }
    method = msg_data['method']
    if method in SANITIZE:
        msg_data = copy.deepcopy(msg_data)
        args_to_sanitize = SANITIZE[method]
        for arg in args_to_sanitize:
            try:
                msg_data['args'][arg] = "<SANITIZED>"
            except KeyError:
                pass

    return log_func(msg, msg_data)
