CREATE TABLE dns_domains (
    created_at DATETIME,
    updated_at DATETIME,
    deleted_at DATETIME,
    deleted BOOLEAN,
    domain VARCHAR(512) CHARACTER SET latin1 NOT NULL,
    scope VARCHAR(255),
    availability_zone VARCHAR(255),
    project_id VARCHAR(255),
    PRIMARY KEY (domain),
    CHECK (deleted IN (0, 1)),
    FOREIGN KEY(project_id) REFERENCES projects (id)
);
