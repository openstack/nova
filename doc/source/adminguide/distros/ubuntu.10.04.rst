
Step 1: Install dependencies
----------------------------
Grab the latest code from launchpad:

::
    bzr clone lp:nova

Here's a script you can use to install (and then run) Nova on Ubuntu or Debian (when using Debian, edit nova.sh to have USE_PPA=0):

.. todo:: give a link to a stable releases page

Step 2: Install dependencies
----------------------------

Nova requires rabbitmq for messaging and optionally you can use redis for storing state, so install these first.

*Note:* You must have sudo installed to run these commands as shown here.

::

    sudo apt-get install rabbitmq-server redis-server


You'll see messages starting with "Reading package lists... Done" and you must confirm by typing Y that you want to continue.

If you're running on Ubuntu 10.04, you'll need to install Twisted and python-gflags which is included in the OpenStack PPA.

::

    sudo apt-get install python-twisted

    sudo apt-key adv --keyserver keyserver.ubuntu.com --recv-keys 95C71FE2
    sudo sh -c 'echo "deb http://ppa.launchpad.net/openstack/openstack-ppa/ubuntu lucid main" > /etc/apt/sources.list.d/openstackppa.list'
    sudo apt-get update && sudo apt-get install python-gflags


Once you've done this, continue at Step 3 here: :doc:`../single.node.install`
