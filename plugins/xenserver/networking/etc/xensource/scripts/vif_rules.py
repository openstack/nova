#!/usr/bin/env python
from os import system, popen4
import sys
import simplejson as json
from itertools import chain

# order is important, mmmkay? 1 is domid, 2  command, 3 is vif
# when we add rules, we delete first, to make sure we only keep the one rule we need

def main():
  fin,fout = popen4("/usr/bin/xenstore-ls /local/domain/%s/vm-data/networking" % sys.argv[1] )
  macs = fout.read().split("\n")[0:-1]

  for mac in macs:
    m = mac.split("=")[0].strip()
    fin,fout = popen4("/usr/bin/xenstore-read /local/domain/%s/vm-data/networking/%s" % (sys.argv[1],m))
    mjson = json.loads(fout.read())
    for ip in mjson['ips']:
      if mjson["label"] == "public":
        label = 0
      else:
        label = 1

      VIF = "vif%s.%s" % (sys.argv[1],label)
        
      if (len(sys.argv) == 4 and sys.argv[3] == VIF) or (len(sys.argv) == 3):
        run_rules(
          IP = ip['ip'], 
          VIF = VIF, 
          MAC = mjson['mac'], 
          STATUS = (sys.argv[2] == 'online') and '-A' or '-D' 
        )

def run_rules(**kwargs):
  map(system, chain(ebtables(**kwargs), arptables(**kwargs), iptables(**kwargs) ))

def iptables(**kwargs):
  return [
    "/sbin/iptables -D FORWARD -m physdev --physdev-in %s -s %s -j ACCEPT 2>&1 > /dev/null" % ( kwargs['VIF'], kwargs['IP']),
    "/sbin/iptables %s FORWARD -m physdev --physdev-in %s -s %s -j ACCEPT" % (kwargs['STATUS'], kwargs['VIF'], kwargs['IP'])
  ]
  
def arptables(**kwargs):
  return [
    "/sbin/arptables -D FORWARD --opcode Request --in-interface %s --source-ip %s --source-mac %s -j ACCEPT 2>&1 > /dev/null" % (kwargs['VIF'], kwargs['IP'], kwargs['MAC']),
    "/sbin/arptables -D FORWARD --opcode Reply --in-interface %s --source-ip %s --source-mac %s -j ACCEPT 2>&1 > /dev/null" % (kwargs['VIF'], kwargs['IP'], kwargs['MAC']),
    "/sbin/arptables %s FORWARD --opcode Request --in-interface %s --source-ip %s --source-mac %s -j ACCEPT" % (kwargs['STATUS'], kwargs['VIF'], kwargs['IP'], kwargs['MAC']),
    "/sbin/arptables %s FORWARD --opcode Reply --in-interface %s --source-ip %s --source-mac %s -j ACCEPT" % (kwargs['STATUS'], kwargs['VIF'], kwargs['IP'], kwargs['MAC'])
  ]

def ebtables(**kwargs):
  cmds = [
    "/sbin/ebtables -D FORWARD -p 0806 -o %s --arp-ip-dst %s -j ACCEPT 2>&1 >> /dev/null" % (kwargs['VIF'], kwargs['IP']),
    "/sbin/ebtables -D FORWARD -p 0800 -o %s --ip-dst %s -j ACCEPT 2>&1 >> /dev/null" % (kwargs['VIF'], kwargs['IP']),
    "/sbin/ebtables %s FORWARD -p 0806 -o %s --arp-ip-dst %s -j ACCEPT 2>&1 " % (kwargs['STATUS'], kwargs['VIF'], kwargs['IP']),
    "/sbin/ebtables %s FORWARD -p 0800 -o %s --ip-dst %s -j ACCEPT 2>&1 " % (kwargs['STATUS'], kwargs['VIF'], kwargs['IP'])
  ]
  if kwargs['STATUS'] == "-A":
    cmds.append("/sbin/ebtables -D FORWARD -s ! %s -i %s -j DROP 2>&1 > /dev/null" % (kwargs['MAC'], kwargs['VIF']))
    cmds.append("/sbin/ebtables -I FORWARD 1 -s ! %s -i %s -j DROP" % (kwargs['MAC'], kwargs['VIF']))
  else:
    cmds.append("/sbin/ebtables %s FORWARD -s ! %s -i %s -j DROP" % (kwargs['STATUS'], kwargs['MAC'], kwargs['VIF']))
  return cmds

def usage():
  print "Usage: slice_vifs.py <DOMID> <online|offline> optional: <vif>"

if __name__ == "__main__":
  if len(sys.argv) < 3:
    usage()
  else:
    main()
