Threading model
===============

All OpenStack services use *green thread* model of threading, implemented 
through using the Python `eventlet <http://eventlet.net/>`_ and 
`greenlet <http://packages.python.org/greenlet/>`_ libraries.

Green threads use a cooperative model of threading: thread context 
switches can only occur when specific eventlet or greenlet library calls are 
made (e.g., sleep, certain I/O calls). From the operating system's point of 
view, each OpenStack service runs in a single thread. 

The use of green threads reduces the likelihood of race conditions, but does
not completely eliminate them. In some cases, you may need to use the 
``@utils.synchronized(...)`` decorator to avoid races.


