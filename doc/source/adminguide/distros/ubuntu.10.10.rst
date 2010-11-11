Installing on Ubuntu Maverick 10.10
====================================
Single Machine Installation (Ubuntu 10.10)

While we wouldn't expect you to put OpenStack Compute into production on a non-LTS version of Ubuntu, these instructions are up-to-date with the latest version of Ubuntu.

Make sure you are running Ubuntu 10.10 so that the packages will be available. This install requires more than 70 MB of free disk space.

These instructions are based on Soren Hansen's blog entry, Openstack on Maverick. A script is in progress as well.

Step 1: Install required prerequisites
--------------------------------------
Nova requires rabbitmq for messaging and redis for storing state (for now), so we'll install these first.::

    sudo apt-get install rabbitmq-server redis-server

You'll see messages starting with "Reading package lists... Done" and you must confirm by typing Y that you want to continue.

Step 2: Install Nova packages available in Maverick Meerkat
-----------------------------------------------------------
Type or copy/paste in the following line to get the packages that you use to run OpenStack Compute.::

    sudo apt-get install python-nova
    sudo apt-get install nova-api nova-objectstore nova-compute nova-scheduler nova-network euca2ools unzip

You'll see messages starting with "Reading package lists... Done" and you must confirm by typing Y that you want to continue. This operation may take a while as many dependent packages will be installed. Note: there is a dependency problem with python-nova which can be worked around by installing first.

When the installation is complete, you'll see the following lines confirming:::

    Adding system user `nova' (UID 106) ...
    Adding new user `nova' (UID 106) with group `nogroup' ...
    Not creating home directory `/var/lib/nova'.
    Setting up nova-scheduler (0.9.1~bzr331-0ubuntu2) ...
     * Starting nova scheduler nova-scheduler
    WARNING:root:Starting scheduler node
       ...done.
    Processing triggers for libc-bin ...
    ldconfig deferred processing now taking place
    Processing triggers for python-support ...

Once you've done this, continue at Step 3 here: :doc:`../single.node.install`
