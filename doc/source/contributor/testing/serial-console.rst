
======================
Testing Serial Console
======================

The main aim of this feature is exposing an interactive web-based
serial consoles through a web-socket proxy.
This page describes how to test it from a devstack environment.

---------------------------------
Setting up a devstack environment
---------------------------------

For instructions on how to setup devstack with serial console support enabled
see `this guide
<https://docs.openstack.org/devstack/latest/guides/nova.html#nova-serialproxy>`_.

---------------
Testing the API
---------------

Starting a new instance.

.. code-block:: bash

  # cd devstack && . openrc
  # nova boot --flavor 1 --image cirros-0.3.2-x86_64-uec cirros1

Nova provides a command `nova get-serial-console` which will returns a
URL with a valid token to connect to the serial console of VMs.

.. code-block:: bash

  # nova get-serial-console cirros1
  +--------+-----------------------------------------------------------------+
  | Type   | Url                                                             |
  +--------+-----------------------------------------------------------------+
  | serial | ws://127.0.0.1:6083/?token=5f7854b7-bf3a-41eb-857a-43fc33f0b1ec |
  +--------+-----------------------------------------------------------------+

Currently nova does not provide any client able to connect from an
interactive console through a web-socket.
A simple client for *test purpose* can be written with few lines of Python.

.. code-block:: python

  # sudo easy_install ws4py || sudo pip install ws4py
  # cat >> client.py <<EOF
  import sys
  from ws4py.client.threadedclient import WebSocketClient
  class LazyClient(WebSocketClient):
      def run(self):
          try:
              while not self.terminated:
                  try:
                      b = self.sock.recv(4096)
                      sys.stdout.write(b)
                      sys.stdout.flush()
                  except: # socket error expected
                      pass
          finally:
              self.terminate()
  if __name__ == '__main__':
      if len(sys.argv) != 2 or not sys.argv[1].startswith("ws"):
          print "Usage %s: Please use websocket url"
          print "Example: ws://127.0.0.1:6083/?token=xxx"
          exit(1)
      try:
          ws = LazyClient(sys.argv[1], protocols=['binary'])
          ws.connect()
          while True:
              # keyboard event...
              c = sys.stdin.read(1)
              if c:
                  ws.send(c)
          ws.run_forever()
      except KeyboardInterrupt:
          ws.close()
  EOF

.. code-block:: bash

  # python client.py ws://127.0.0.1:6083/?token=5f7854b7-bf3a-41eb-857a-43fc33f0b1ec
  <enter>
  cirros1 login
