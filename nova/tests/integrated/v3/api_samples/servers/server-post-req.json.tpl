{
    "server" : {
        "name" : "new-server-test",
        "image_ref" : "%(glance_host)s/images/%(image_id)s",
        "flavor_ref" : "%(host)s/flavors/1",
        "metadata" : {
            "My Server Name" : "Apache1"
        }
    }
}
