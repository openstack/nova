TARNAME=openstack-nova
SPECFILE=openstack-nova.spec

sources: $(SPECFILE)
	git archive --format=tar --prefix=$(TARNAME)/ HEAD > $(TARNAME).tar
	mkdir -p $(TARNAME)
	cp openstack-nova-*.service $(TARNAME)
	cp nova-dist.conf $(TARNAME)
	cp nova-ifc-template $(TARNAME)
	cp nova-polkit.pkla $(TARNAME)
	cp nova-polkit.rules $(TARNAME)
	cp nova-sudoers $(TARNAME)
	cp nova.logrotate $(TARNAME)
	tar --owner=0 --group=0 -rf $(TARNAME).tar $(TARNAME)/openstack-nova-*.service $(TARNAME)/nova-dist.conf $(TARNAME)/nova-ifc-template $(TARNAME)/nova-polkit.pkla $(TARNAME)/nova-polkit.rules $(TARNAME)/nova-sudoers $(TARNAME)/nova.logrotate
	gzip -f -9 $(TARNAME).tar
	rm -fr $(TARNAME)
	

rpm: sources
	rpmbuild -ta $(TARNAME).tar.gz
