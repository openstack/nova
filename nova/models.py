from sqlalchemy.orm import relationship, backref, validates
from sqlalchemy import Table, Column, Integer, String, MetaData, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base
from auth import *

Base = declarative_base()

class User(Base):
    # sqlalchemy
    __tablename__ = 'users'
    sid = Column(String, primary_key=True)

    # backwards compatibility
    @classmethod
    def safe_id(cls, obj):
        """Safe get object id

        This method will return the id of the object if the object
        is of this class, otherwise it will return the original object.
        This allows methods to accept objects or ids as paramaters.

        """
        if isinstance(obj, cls):
            return obj.id
        else:
            return obj

#    def __init__(self, id, name, access, secret, admin):
#        self.id = id
#        self.name = name
#        self.access = access
#        self.secret = secret
#        self.admin = admin

    def __getattr__(self, name):
        if name == 'id':
            return self.uid
        else:  raise AttributeError, name
    
    def is_superuser(self):
        return AuthManager().is_superuser(self)

    def is_admin(self):
        return AuthManager().is_admin(self)

    def has_role(self, role):
        return AuthManager().has_role(self, role)

    def add_role(self, role):
        return AuthManager().add_role(self, role)

    def remove_role(self, role):
        return AuthManager().remove_role(self, role)

    def is_project_member(self, project):
        return AuthManager().is_project_member(self, project)

    def is_project_manager(self, project):
        return AuthManager().is_project_manager(self, project)

    def generate_key_pair(self, name):
        return AuthManager().generate_key_pair(self.id, name)

    def create_key_pair(self, name, public_key, fingerprint):
        return AuthManager().create_key_pair(self.id,
                                             name,
                                             public_key,
                                             fingerprint)

    def get_key_pair(self, name):
        return AuthManager().get_key_pair(self.id, name)

    def delete_key_pair(self, name):
        return AuthManager().delete_key_pair(self.id, name)

    def get_key_pairs(self):
        return AuthManager().get_key_pairs(self.id)

    def __repr__(self):
        return "User('%s', '%s', '%s', '%s', %s)" % (self.id,
                                                     self.name,
                                                     self.access,
                                                     self.secret,
                                                     self.admin)



class Project(Base):
    __tablename__ = 'projects'
    sid = Column(String, primary_key=True)

class Image(Base):
    __tablename__ = 'images'
    user_sid = Column(String, ForeignKey('users.sid'), nullable=False)
    project_sid = Column(String, ForeignKey('projects.sid'), nullable=False)

    sid = Column(String, primary_key=True)
    image_type = Column(String)
    public = Column(Boolean, default=False)
    state = Column(String)
    location = Column(String)
    arch = Column(String)
    default_kernel_sid = Column(String)
    default_ramdisk_sid = Column(String)

    created_at = Column(DateTime)
    updated_at = Column(DateTime) # auto update on change FIXME


    @validates('image_type')
    def validate_image_type(self, key, image_type):
        assert(image_type in ['machine', 'kernel', 'ramdisk', 'raw'])

    @validates('state')
    def validate_state(self, key, state):
        assert(state in ['available', 'pending', 'disabled'])

    @validates('default_kernel_sid')
    def validate_kernel_sid(self, key, val):
        if val != 'machine':
            assert(val is None)

    @validates('default_ramdisk_sid')
    def validate_ramdisk_sid(self, key, val):
        if val != 'machine':
            assert(val is None)

class Network(Base):
    __tablename__ = 'networks'
    id = Column(Integer, primary_key=True)
    bridge = Column(String)
    vlan = Column(String)
    #vpn_port = Column(Integer)
    project_sid = Column(String, ForeignKey('projects.sid'), nullable=False)

class PhysicalNode(Base):
    __tablename__ = 'physical_nodes'
    id = Column(Integer, primary_key=True)

class Instance(Base):
    __tablename__ = 'instances'
    id = Column(Integer, primary_key=True)

    user_sid = Column(String, ForeignKey('users.sid'), nullable=False)
    project_sid = Column(String, ForeignKey('projects.sid'))

    image_sid = Column(Integer, ForeignKey('images.sid'), nullable=False)
    kernel_sid = Column(String, ForeignKey('images.sid'), nullable=True)
    ramdisk_sid = Column(String, ForeignKey('images.sid'), nullable=True)

    launch_index = Column(Integer)
    key_name = Column(String)
    key_data = Column(Text)

    state = Column(String)

    hostname = Column(String)
    physical_node_id = Column(Integer)

    instance_type = Column(Integer)

    user_data = Column(Text)

#    user = relationship(User, backref=backref('instances', order_by=id))
#    ramdisk = relationship(Ramdisk, backref=backref('instances', order_by=id))
#    kernel = relationship(Kernel, backref=backref('instances', order_by=id))
#    project = relationship(Project, backref=backref('instances', order_by=id))

#TODO - see Ewan's email about state improvements
    # vmstate_state = running, halted, suspended, paused
    # power_state = what we have
    # task_state = transitory and may trigger power state transition

    @validates('state')
    def validate_state(self, key, state):
        assert(state in ['nostate', 'running', 'blocked', 'paused', 'shutdown', 'shutoff', 'crashed'])

class Volume(Base):
    __tablename__ = 'volumes'
    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer)
    blade_id = Column(Integer)


if __name__ == '__main__':
    from sqlalchemy import create_engine
    engine = create_engine('sqlite:///:memory:', echo=True)
    Base.metadata.create_all(engine) 

    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=engine)
    session = Session()

    instance = Instance(image_sid='as', ramdisk_sid='AS', user_sid='anthony')
    user = User(sid='anthony')
    session.add(instance)
    session.commit()

