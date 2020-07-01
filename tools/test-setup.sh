#!/bin/bash -xe

# This script will be run by OpenStack CI before unit tests are run,
# it sets up the test system as needed.
# Developers should setup their test systems in a similar way.

# This setup needs to be run as a user that can run sudo.

# The root password for the MySQL database; pass it in via
# MYSQL_ROOT_PW.
DB_ROOT_PW=${MYSQL_ROOT_PW:-insecure_slave}

# This user and its password are used by the tests, if you change it,
# your tests might fail.
DB_USER=openstack_citest
DB_PW=openstack_citest

sudo -H mysqladmin -u root password $DB_ROOT_PW

# It's best practice to remove anonymous users from the database.  If
# an anonymous user exists, then it matches first for connections and
# other connections from that host will not work.
sudo -H mysql -u root -p$DB_ROOT_PW -h localhost -e "
    DELETE FROM mysql.user WHERE User='';
    FLUSH PRIVILEGES;
    CREATE USER '$DB_USER'@'%' IDENTIFIED BY '$DB_PW';
    GRANT ALL PRIVILEGES ON *.* TO '$DB_USER'@'%' WITH GRANT OPTION;"

# Now create our database.
mysql -u $DB_USER -p$DB_PW -h 127.0.0.1 -e "
    SET default_storage_engine=MYISAM;
    DROP DATABASE IF EXISTS openstack_citest;
    CREATE DATABASE openstack_citest CHARACTER SET utf8;"

# Same for PostgreSQL

# Setup user
root_roles=$(sudo -H -u postgres psql -t -c "
   SELECT 'HERE' from pg_roles where rolname='$DB_USER'")
if [[ ${root_roles} == *HERE ]];then
    sudo -H -u postgres psql -c "ALTER ROLE $DB_USER WITH SUPERUSER LOGIN PASSWORD '$DB_PW'"
else
    sudo -H -u postgres psql -c "CREATE ROLE $DB_USER WITH SUPERUSER LOGIN PASSWORD '$DB_PW'"
fi

# Store password for tests
cat << EOF > $HOME/.pgpass
*:*:*:$DB_USER:$DB_PW
EOF
chmod 0600 $HOME/.pgpass

# Now create our database
psql -h 127.0.0.1 -U $DB_USER -d template1 -c "DROP DATABASE IF EXISTS openstack_citest"
createdb -h 127.0.0.1 -U $DB_USER -l C -T template0 -E utf8 openstack_citest
