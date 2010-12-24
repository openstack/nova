#!/bin/bash

DIR=/opt/nova-2010.1

function inc_assigned(){
   assigned=`expr $assigned + 1`
}


# 1. 認証情報の読み込み
. $DIR/novarc

# 3. 仮想マシンの起動
#
ret=`euca-run-instances -t m1.small -k testkey ami-centos`
#ret=`euca-run-instances -t m1.small -k testkey ami-tiny`

# 4. 仮想マシン用IPの確保
# 未登録なら登録しておく
registered=`euca-describe-addresses`
for ip in 172.19.0.134 172.19.0.135 172.19.0.136 172.19.0.137 ; do
    
  not_registered=`echo $registered | grep $ip`
  if [ "" == "$not_registered" ]; then
     echo "[INFO] registed $ip"
     $DIR/bin/nova-manage floating create `hostname` $ip
  fi
done

# 5. IPの割当
echo 0 > /tmp/demo-runinstance
euca-describe-addresses | grep -v reserved | while read line; do
    # 割り当てられてないものを仮想マシンに割り当てる
    ip=`echo $line | cut -d ' ' -f 2`
    id=`echo $ret | cut -d ' ' -f 5`
    if [ "" == "`echo $id | grep i- `" ] ; then
          echo "[INFO] try again" $ret
          break
    fi
    echo "[INFO] assigned to ipaddr($ip) to instance($id) "
    euca-associate-address -i $id $ip
    echo 1 > /tmp/demo-runinstance
    break
done

echo $assigned
if [ 0 -eq "`cat /tmp/demo-runinstance`" ] ; then
   echo "[INFO] address is full."
fi
rm -rf /tmp/demo-runinstance


# 6. FWの設定
euca-authorize -P tcp -p 22 default 2> /dev/null > /dev/null
euca-authorize -P tcp -p 80 default 2> /dev/null > /dev/null
euca-authorize -P tcp -p 5555 default 2> /dev/null > /dev/null

