Installing Nova on a Single Host
================================

Nova can be run on a single machine, and it is recommended that new users practice managing this type of installation before graduating to multi node systems.

The fastest way to get a test cloud running is through our :doc:`../quickstart`.  But for more detail on installing the system read this doc.


Step 1 and 2: Get the latest Nova code system software
------------------------------------------------------

Depending on your system, the method for accomplishing this varies

.. toctree::
   :maxdepth: 1

   distros/ubuntu.10.04
   distros/ubuntu.10.10
   distros/others


Step 3: Build and install Nova services
---------------------------------------

Switch to the base nova source directory.

Then type or copy/paste in the following line to compile the Python code for OpenStack Compute.

::

    sudo python setup.py build
    sudo python setup.py install


When the installation is complete, you'll see the following lines:

::

    Installing nova-network script to /usr/local/bin
    Installing nova-volume script to /usr/local/bin
    Installing nova-objectstore script to /usr/local/bin
    Installing nova-manage script to /usr/local/bin
    Installing nova-scheduler script to /usr/local/bin
    Installing nova-dhcpbridge script to /usr/local/bin
    Installing nova-compute script to /usr/local/bin
    Installing nova-instancemonitor script to /usr/local/bin
    Installing nova-api script to /usr/local/bin
    Installing nova-import-canonical-imagestore script to /usr/local/bin

    Installed /usr/local/lib/python2.6/dist-packages/nova-2010.1-py2.6.egg
    Processing dependencies for nova==2010.1
    Finished processing dependencies for nova==2010.1


Step 4: Create a Nova administrator
-----------------------------------
Type or copy/paste in the following line to create a user named "anne."::

    sudo nova-manage user admin anne

You see an access key and a secret key export, such as these made-up ones:::

    export EC2_ACCESS_KEY=4e6498a2-blah-blah-blah-17d1333t97fd
    export EC2_SECRET_KEY=0a520304-blah-blah-blah-340sp34k05bbe9a7

Step 5: Create the network 
--------------------------

Type or copy/paste in the following line to create a network prior to creating a project. 

::

    sudo nova-manage network create 10.0.0.0/8 1 64

For this command, the IP address is the cidr notation for your netmask, such as 192.168.1.0/24. The value 1 is the total number of networks you want made, and the 64 value is the total number of ips in all networks.

After running this command, entries are made in the 'networks' and 'fixed_ips' table in the database.

Step 6: Create a project with the user you created
--------------------------------------------------
Type or copy/paste in the following line to create a project named IRT (for Ice Road Truckers, of course) with the newly-created user named anne.

::

    sudo nova-manage project create IRT anne

::

    Generating RSA private key, 1024 bit long modulus
    .....++++++
    ..++++++
    e is 65537 (0x10001)
    Using configuration from ./openssl.cnf
    Check that the request matches the signature
    Signature ok
    The Subject's Distinguished Name is as follows
    countryName           :PRINTABLE:'US'
    stateOrProvinceName   :PRINTABLE:'California'
    localityName          :PRINTABLE:'MountainView'
    organizationName      :PRINTABLE:'AnsoLabs'
    organizationalUnitName:PRINTABLE:'NovaDev'
    commonName            :PRINTABLE:'anne-2010-10-12T21:12:35Z'
    Certificate is to be certified until Oct 12 21:12:35 2011 GMT (365 days)

    Write out database with 1 new entries
    Data Base Updated


Step 7: Unzip the nova.zip
--------------------------

You should have a nova.zip file in your current working directory. Unzip it with this command:

::

    unzip nova.zip


You'll see these files extract.

::

    Archive:  nova.zip
     extracting: novarc
     extracting: pk.pem
     extracting: cert.pem
     extracting: nova-vpn.conf
     extracting: cacert.pem


Step 8: Source the rc file
--------------------------
Type or copy/paste the following to source the novarc file in your current working directory.

::

    . novarc


Step 9: Pat yourself on the back :)
-----------------------------------
Congratulations, your cloud is up and running, you’ve created an admin user, created a network, retrieved the user's credentials and put them in your environment.

Now you need an image.


Step 9: Get an image
--------------------
To make things easier, we've provided a small image on the Rackspace CDN. Use this command to get it on your server.

::

    wget http://c2477062.cdn.cloudfiles.rackspacecloud.com/images.tgz


::

    --2010-10-12 21:40:55--  http://c2477062.cdn.cloudfiles.rackspacecloud.com/images.tgz
    Resolving cblah2.cdn.cloudfiles.rackspacecloud.com... 208.111.196.6, 208.111.196.7
    Connecting to cblah2.cdn.cloudfiles.rackspacecloud.com|208.111.196.6|:80... connected.
    HTTP request sent, awaiting response... 200 OK
    Length: 58520278 (56M) [appication/x-gzip]
    Saving to: `images.tgz'

    100%[======================================>] 58,520,278  14.1M/s   in 3.9s

    2010-10-12 21:40:59 (14.1 MB/s) - `images.tgz' saved [58520278/58520278]



Step 10: Decompress the image file
----------------------------------
Use this command to extract the image files:::

    tar xvzf images.tgz

You get a directory listing like so:::

    images
    |-- aki-lucid
    |   |-- image
    |   `-- info.json
    |-- ami-tiny
    |   |-- image
    |   `-- info.json
    `-- ari-lucid
        |-- image
        `-- info.json

Step 11: Send commands to upload sample image to the cloud
----------------------------------------------------------

Type or copy/paste the following commands to create a manifest for the kernel.::

    euca-bundle-image -i images/aki-lucid/image -p kernel --kernel true

You should see this in response:::

    Checking image
    Tarring image
    Encrypting image
    Splitting image...
    Part: kernel.part.0
    Generating manifest /tmp/kernel.manifest.xml

Type or copy/paste the following commands to create a manifest for the ramdisk.::

    euca-bundle-image -i images/ari-lucid/image -p ramdisk --ramdisk true

You should see this in response:::

    Checking image
    Tarring image
    Encrypting image
    Splitting image...
    Part: ramdisk.part.0
    Generating manifest /tmp/ramdisk.manifest.xml

Type or copy/paste the following commands to upload the kernel bundle.::

    euca-upload-bundle -m /tmp/kernel.manifest.xml -b mybucket

You should see this in response:::

    Checking bucket: mybucket
    Creating bucket: mybucket
    Uploading manifest file
    Uploading part: kernel.part.0
    Uploaded image as mybucket/kernel.manifest.xml

Type or copy/paste the following commands to upload the ramdisk bundle.::

    euca-upload-bundle -m /tmp/ramdisk.manifest.xml -b mybucket

You should see this in response:::

    Checking bucket: mybucket
    Uploading manifest file
    Uploading part: ramdisk.part.0
    Uploaded image as mybucket/ramdisk.manifest.xml

Type or copy/paste the following commands to register the kernel and get its ID.::

    euca-register mybucket/kernel.manifest.xml

You should see this in response:::

    IMAGE   ami-fcbj2non

Type or copy/paste the following commands to register the ramdisk and get its ID.::

    euca-register mybucket/ramdisk.manifest.xml

You should see this in response:::

    IMAGE   ami-orukptrc

Type or copy/paste the following commands to create a manifest for the machine image associated with the ramdisk and kernel IDs that you got from the previous commands.::

    euca-bundle-image -i images/ami-tiny/image -p machine  --kernel ami-fcbj2non --ramdisk ami-orukptrc

You should see this in response:::

    Checking image
    Tarring image
    Encrypting image
    Splitting image...
    Part: machine.part.0
    Part: machine.part.1
    Part: machine.part.2
    Part: machine.part.3
    Part: machine.part.4
    Generating manifest /tmp/machine.manifest.xml

Type or copy/paste the following commands to upload the machine image bundle.::

    euca-upload-bundle -m /tmp/machine.manifest.xml -b mybucket

You should see this in response:::

    Checking bucket: mybucket
    Uploading manifest file
    Uploading part: machine.part.0
    Uploading part: machine.part.1
    Uploading part: machine.part.2
    Uploading part: machine.part.3
    Uploading part: machine.part.4
    Uploaded image as mybucket/machine.manifest.xml

Type or copy/paste the following commands to register the machine image and get its ID.::

    euca-register mybucket/machine.manifest.xml

You should see this in response:::

    IMAGE   ami-g06qbntt

Type or copy/paste the following commands to register a SSH keypair for use in starting and accessing the instances.::

    euca-add-keypair mykey > mykey.priv
    chmod 600 mykey.priv

Type or copy/paste the following commands to run an instance using the keypair and IDs that we previously created.::

    euca-run-instances ami-g06qbntt --kernel  ami-fcbj2non --ramdisk ami-orukptrc -k mykey

You should see this in response:::

    RESERVATION     r-0at28z12      IRT
    INSTANCE        i-1b0bh8n       ami-g06qbntt    10.0.0.3        10.0.0.3        scheduling      mykey (IRT, None)      m1.small 2010-10-18 19:02:10.443599

Type or copy/paste the following commands to watch as the scheduler launches, and completes booting your instance.::

    euca-describe-instances

You should see this in response:::

    RESERVATION     r-0at28z12      IRT
    INSTANCE        i-1b0bh8n       ami-g06qbntt    10.0.0.3        10.0.0.3        launching       mykey (IRT, cloud02)   m1.small 2010-10-18 19:02:10.443599

Type or copy/paste the following commands to see when loading is completed and the instance is running.::

    euca-describe-instances

You should see this in response:::

    RESERVATION     r-0at28z12      IRT
    INSTANCE        i-1b0bh8n       ami-g06qbntt    10.0.0.3        10.0.0.3        running mykey (IRT, cloud02)    0      m1.small 2010-10-18 19:02:10.443599

Type or copy/paste the following commands to check that the virtual machine is running.::

    virsh list

You should see this in response:::

    Id Name                 State
    ----------------------------------
    1 2842445831           running

Type or copy/paste the following commands to ssh to the instance using your private key.::

    ssh -i mykey.priv root@10.0.0.3
    

Troubleshooting Installation
----------------------------

If you see an "error loading the config file './openssl.cnf'" it means you can copy the openssl.cnf file to the location where Nova expects it and reboot, then try the command again.

::

    cp /etc/ssl/openssl.cnf ~
    sudo reboot



