#!/bin/bash
PACKAGE=openstack-xen-plugins
THIS_DIR=$(cd $(dirname $0) && pwd)
RPMBUILD_DIR="$THIS_DIR/rpmbuild"

if [ ! -d $RPMBUILD_DIR ]; then
    echo $RPMBUILD_DIR is missing
    exit 1
fi

for dir in BUILD BUILDROOT SRPMS RPMS SOURCES; do
    rm -rf $RPMBUILD_DIR/$dir
    mkdir -p $RPMBUILD_DIR/$dir
done

rm -rf /tmp/$PACKAGE
mkdir /tmp/$PACKAGE
cp -r "$THIS_DIR/../etc/xapi.d" /tmp/$PACKAGE
tar czf $RPMBUILD_DIR/SOURCES/$PACKAGE.tar.gz -C /tmp $PACKAGE

rpmbuild -ba --nodeps --define "_topdir $RPMBUILD_DIR" \
    $RPMBUILD_DIR/SPECS/$PACKAGE.spec
