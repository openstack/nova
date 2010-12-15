Installing the Live CD
======================

If you'd like to set up a sandbox installation of Nova, you can use one of these Live CD images. 

If you don't already have VirtualBox installed, you can download it from http://www.virtualbox.org/wiki/Downloads.
 
Download the zip or iso file and then follow these steps to try Nova in a virtual environment.

http://c0047913.cdn1.cloudfiles.rackspacecloud.com/OpenStackNova.x86_64-2010.1.2.iso (OpenSUSE image; root password is "linux" for this image)

http://c0028699.cdn1.cloudfiles.rackspacecloud.com/nova-vm.zip (~900 MB) (log in information is nova/nova)

Once a VM is configured and started, here are the basics:

 #. Login to Ubuntu using ID nova and Password nova.

 #. Switch to running as sudo (enter nova when prompted for the password)::

    sudo -s

 #. To run Nova for the first time, enter::

    cd /var/openstack/

 #. Now that you're in the correct directory, enter::

    ./nova.sh run

    .. image:: images/novashvirtually.png

If it's already running, use screen -ls, and when the nova screen is presented,then enter screen -d -r nova.

These are the steps to get an instance running (the image is already provided in this environment). Enter these commands in the "test" screen.

::

 euca-add-keypair test > test.pem
 chmod 600 test.pem
 euca-run-instances -k test -t m1.tiny ami-tiny
 euca-describe-instances

 ssh -i test.pem root@10.0.0.3

To see output from the various workers, switch screen windows with Ctrl+A " (quotation mark). 

    .. image:: images/novascreens.png 

