#!/bin/bash

DIR=/opt/nova-2010.1

# 1. 管理者ユーザを作成する
# nova-manage user admin ユーザ名 access-key secret-key
#
#$DIR/bin/nova-manage user admin admin admin admin

# 2. プロジェクトを作成する
# nova-manage create project プロジェクト名 プロジェクトに属するユーザ名
#
#$DIR/bin/nova-manage project create admin admin

# 3. クラウドを使うための認証情報を生成する
# nova-manage project environment プロジェクト名  ユーザ名 認証情報を格納するファイル
#
#$DIR/bin/nova-manage project environment admin admin $DIR/novarc

# 4. 認証情報の読み込み
. $DIR/novarc

# 5. プロジェクト用仮想マシンネットワークの作成を行う
# nova-manage user admin ユーザ名 access-key secret-key
#
$DIR/bin/nova-manage network  create 10.0.0.0/8 3 16

# 6. 初回ログインにはSSHの公開鍵認証が必要
#
if [ "" == "`euca-describe-keypairs | grep testkey`" ]; then
    euca-add-keypair  testkey > testkey.pem
fi

# 7. 
for i in 172.19.0.134 172.19.0.135 172.19.0.136 172.19.0.137 ; do
    sudo ip addr del $i dev eth0 2> /dev/null
done


