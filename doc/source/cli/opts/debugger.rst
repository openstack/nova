.. option:: --remote_debug-host REMOTE_DEBUG_HOST

    Debug host (IP or name) to connect to. This command line parameter is used
    when you want to connect to a nova service via a debugger running on a
    different host. Note that using the remote debug option changes how Nova
    uses the eventlet library to support async IO. This could result in
    failures that do not occur under normal operation. Use at your own risk.

.. option:: --remote_debug-port REMOTE_DEBUG_PORT

    Debug port to connect to. This command line parameter allows you to specify
    the port you want to use to connect to a nova service via a debugger
    running on different host. Note that using the remote debug option changes
    how Nova uses the eventlet library to support async IO. This could result
    in failures that do not occur under normal operation. Use at your own risk.
