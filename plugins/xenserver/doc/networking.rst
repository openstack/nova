Multi Tenancy Networking Protections in XenServer
=================================================

The purpose of the vif_rules script is to allow multi-tenancy on a XenServer
host.  In a multi-tenant cloud environment a host machine needs to be able to
enforce network isolation amongst guest instances, at both layer two and layer
three. The rules prevent guests from taking and using unauthorized IP addresses,
sniffing other guests traffic, and prevents ARP poisoning attacks.  This current
revision only supports IPv4, but will support IPv6 in the future.

Kernel Requirements
===================

- physdev module
- arptables support
- ebtables support
- iptables support

If the kernel doesn't support these, you will need to obtain the Source RPMS for
the proper version of XenServer to recompile the dom0 kernel.

XenServer Requirements (32-bit dom0)
====================================

- arptables 32-bit rpm 
- ebtables 32-bit rpm
- python-simplejson

XenServer Environment Specific Notes 
====================================

- XenServer 5.5 U1 based on the 2.6.18 kernel didn't include physdev module
  support.  Support for this had to be recompiled into the kernel.
- XenServer 5.6 based on the 2.6.27 kernel didn't include physdev, ebtables, or
  arptables.
- XenServer 5.6 FP1 didn't include physdev, ebtables, or arptables but they do
  have a Cloud Supplemental pack available to partners which swaps out the
  kernels for kernels that support the networking rules.  

How it works - tl;dr
====================

iptables, ebtables, and arptables drop rules are applied to all forward chains
on the host.  These are applied at boot time with an init script.  They ensure
all forwarded packets are dropped by default.  Allow rules are then applied to
the instances to ensure they have permission to talk on the internet.

How it works - Long
===================

Any time an underprivileged domain or domU is started or stopped, it gets a
unique domain id (dom_id).  This dom_id is utilized in a number of places, one
of which is it's assigned to the virtual interface (vif).  The vifs are attached
to the bridge that is attached to the physical network.  For instance, if you
had a public bridge attached to eth0 and your domain id was 5, your vif would be
vif5.0.  

The networking rules are applied to the VIF directly so they apply at the lowest
level of the networking stack.  Because the VIF changes along with the domain id
on any start, stop, or reboot of the instance, the rules need to be removed and
re-added any time that occurs.   

Because the dom_id can change often, the vif_rules script is hooked into the
/etc/xensource/scripts/vif script that gets called anytime an instance is
started, or stopped, which includes pauses and resumes.

Examples of the rules ran for the host on boot:

iptables -P FORWARD DROP 
iptables -A FORWARD -m physdev --physdev-in eth0 -j ACCEPT
ebtables -P FORWARD DROP
ebtables -A FORWARD -o eth0 -j ACCEPT
arptables -P FORWARD DROP 
arptables -A FORWARD --opcode Request --in-interface eth0 -j ACCEPT
arptables -A FORWARD --opcode Reply --in-interface eth0 -j ACCEPT

Examples of the rules that are ran per instance state change:

iptables -A FORWARD -m physdev --physdev-in vif1.0 -s 10.1.135.22/32 -j ACCEPT
arptables -A FORWARD --opcode Request --in-interface "vif1.0" \
          --source-ip 10.1.135.22 -j ACCEPT
arptables -A FORWARD --opcode Reply --in-interface "vif1.0" \
          --source-ip 10.1.135.22 --source-mac 9e:6e:cc:19:7f:fe -j ACCEPT
ebtables -A FORWARD -p 0806 -o vif1.0 --arp-ip-dst 10.1.135.22 -j ACCEPT
ebtables -A FORWARD -p 0800 -o vif1.0 --ip-dst 10.1.135.22 -j ACCEPT 
ebtables -I FORWARD 1 -s ! 9e:6e:cc:19:7f:fe -i vif1.0 -j DROP

Typically when you see a vif, it'll look like vif<domain id>.<network bridge>.
vif2.1 for example would be domain 2 on the second interface.

The vif_rules.py script needs to pull information about the IPs and MAC
addresses assigned to the instance.  The current implementation assumes that
information is put into the VM Record into the xenstore-data key in a JSON
string.  The vif_rules.py script reads out of the JSON string to determine the
IPs, and MAC addresses to protect.  

An example format is given below:

# xe vm-param-get uuid=<uuid> param-name=xenstore-data 
xenstore-data (MRW):
vm-data/networking/4040fa7292e4:
{"label": "public",
 "ips": [{"netmask":"255.255.255.0", 
          "enabled":"1", 
          "ip":"173.200.100.10"}], 
 "mac":"40:40:fa:72:92:e4",
 "gateway":"173.200.100.1", 
 "vm_id":"123456",
 "dns":["72.3.128.240","72.3.128.241"]};

vm-data/networking/40402321c9b8:
{"label":"private",
 "ips":[{"netmask":"255.255.224.0",
         "enabled":"1", 
         "ip":"10.177.10.10"}],
 "routes":[{"route":"10.176.0.0",
            "netmask":"255.248.0.0",
            "gateway":"10.177.10.1"},
           {"route":"10.191.192.0",
            "netmask":"255.255.192.0",
            "gateway":"10.177.10.1"}],
 "mac":"40:40:23:21:c9:b8"}

The key is used for two purposes.  One, the vif_rules.py script will read from
it to apply the rules needed after parsing the JSON.  The second is that because
it's put into the xenstore-data field, the xenstore will be populated with this
data on boot.  This allows a guest agent the ability to read out data about the
instance and apply configurations as needed.  

Installation
============

- Copy host-rules into /etc/init.d/ and make sure to chmod +x host-rules.
- Run 'chkconfig host-rules on' to add the init script to start up.
- Copy vif_rules.py into /etc/xensource/scripts
- Patch /etc/xensource/scripts/vif using the supplied patch file.  It may vary
  for different versions of XenServer but it should be pretty self explanatory.
  It calls the vif_rules.py script on domain creation and tear down.
- Run '/etc/init.d/host-rules start' to start up the host based rules.
- The instance rules will then fire on creation of the VM as long as the correct
  JSON is in place.
- You can check to see if the rules are in place with: iptables --list,
  arptables --list, or ebtables --list

