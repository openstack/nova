{
    "server" : {
        "name" : "new-server-test",
        "image_ref" : "%(host)s/openstack/images/%(image_id)s",
        "flavor_ref" : "%(host)s/openstack/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        },
        "user_data" : "%(user_data)s"
    }
}
