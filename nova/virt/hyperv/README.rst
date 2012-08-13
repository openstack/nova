Hyper-V Volumes Management
=============================================

To enable the  volume features, the first thing that needs to be done is to
enable the iSCSI service on the Windows compute nodes and set it to start
automatically.

sc config msiscsi start= auto
net start msiscsi

In Windows Server 2012, it's important to execute the following commands to
prevent having the volumes being online by default:

diskpart
san policy=OfflineAll
exit

How to check if your iSCSI configuration is working properly:

On your OpenStack controller:

1. Create a volume with e.g. "nova volume-create 1" and note the generated
volume id

On Windows:

2. iscsicli QAddTargetPortal <your_iSCSI_target>
3. iscsicli ListTargets

The output should contain the iqn related to your volume:
iqn.2010-10.org.openstack:volume-<volume_id>

How to test Boot from volume in Hyper-V from the OpenStack dashboard:

1. Fist of all create a volume
2. Get the volume ID of the created volume
3. Upload and untar to the Cloud controller the next VHD image:
http://dev.opennebula.org/attachments/download/482/ttylinux.vhd.gz
4. sudo dd if=/path/to/vhdfileofstep3 
of=/dev/nova-volumes/volume-XXXXX <- Related to the ID of step 2
5. Launch an instance from any image (this is not important because we are
just booting from a volume) from the dashboard, and don't forget to select
boot from volume and select the volume created in step2. Important: Device
name must be "vda".
