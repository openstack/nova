import sys

import lockfile.linklockfile, lockfile.mkdirlockfile, lockfile.pidlockfile

from compliancetest import ComplianceTest
    
class TestLinkLockFile(ComplianceTest):
    class_to_test = lockfile.linklockfile.LinkLockFile

class TestMkdirLockFile(ComplianceTest):
    class_to_test = lockfile.mkdirlockfile.MkdirLockFile

class TestPIDLockFile(ComplianceTest):
    class_to_test = lockfile.pidlockfile.PIDLockFile

# Check backwards compatibility
class TestLinkFileLock(ComplianceTest):
    class_to_test = lockfile.LinkFileLock

class TestMkdirFileLock(ComplianceTest):
    class_to_test = lockfile.MkdirFileLock

try:
    import sqlite3
except ImportError:
    pass
else:
    import lockfile.sqlitelockfile
    class TestSQLiteLockFile(ComplianceTest):
        class_to_test = lockfile.sqlitelockfile.SQLiteLockFile
