#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import hashlib
import os
import time

from facebook.eden.ttypes import SHA1Result, EdenError
from facebook.eden.ttypes import TimeSpec
from .lib import testcase


@testcase.eden_repo_test
class ThriftTest:
    def populate_repo(self):
        self.repo.write_file('hello', 'hola\n')
        self.repo.write_file('adir/file', 'foo!\n')
        self.repo.write_file('bdir/file', 'bar!\n')
        self.repo.symlink('slink', 'hello')
        self.repo.commit('Initial commit.')

    def setUp(self):
        super().setUp()
        self.client = self.get_thrift_client()
        self.client.open()

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def get_loaded_inodes_count(self, path):
        result = self.client.debugInodeStatus(self.mount, path)
        inode_count = 0
        for item in result:
            for inode in item.entries:
                if inode.loaded:
                    inode_count += 1
        return inode_count

    def test_list_mounts(self):
        mounts = self.client.listMounts()
        self.assertEqual(1, len(mounts))

        mount = mounts[0]
        self.assertEqual(self.mount, mount.mountPoint)
        # Currently, edenClientPath is not set.
        self.assertEqual('', mount.edenClientPath)

    def test_get_sha1(self):
        expected_sha1_for_hello = hashlib.sha1(b'hola\n').digest()
        result_for_hello = SHA1Result()
        result_for_hello.set_sha1(expected_sha1_for_hello)

        expected_sha1_for_adir_file = hashlib.sha1(b'foo!\n').digest()
        result_for_adir_file = SHA1Result()
        result_for_adir_file.set_sha1(expected_sha1_for_adir_file)

        self.assertEqual(
            [
                result_for_hello,
                result_for_adir_file,
            ], self.client.getSHA1(self.mount, ['hello', 'adir/file'])
        )

    def test_get_sha1_throws_for_empty_string(self):
        results = self.client.getSHA1(self.mount, [''])
        self.assertEqual(1, len(results))
        self.assert_error(results[0], 'path cannot be the empty string')

    def test_get_sha1_throws_for_directory(self):
        results = self.client.getSHA1(self.mount, ['adir'])
        self.assertEqual(1, len(results))
        self.assert_error(results[0], 'adir: Is a directory')

    def test_get_sha1_throws_for_non_existent_file(self):
        results = self.client.getSHA1(self.mount, ['i_do_not_exist'])
        self.assertEqual(1, len(results))
        self.assert_error(results[0],
                          'i_do_not_exist: No such file or directory')

    def test_get_sha1_throws_for_symlink(self):
        '''Fails because caller should resolve the symlink themselves.'''
        results = self.client.getSHA1(self.mount, ['slink'])
        self.assertEqual(1, len(results))
        self.assert_error(results[0],
                          'slink: file is a symlink: Invalid argument')

    def assert_error(self, sha1result, error_message):
        self.assertIsNotNone(sha1result, msg='Must pass a SHA1Result')
        self.assertEqual(
            SHA1Result.ERROR,
            sha1result.getType(),
            msg='SHA1Result must be an error'
        )
        error = sha1result.get_error()
        self.assertIsNotNone(error)
        self.assertEqual(error_message, error.message)

    def test_glob(self):
        self.assertEqual(
            ['adir/file'], self.client.glob(self.mount, ['a*/file']))
        self.assertCountEqual(
            ['adir/file', 'bdir/file'], self.client.glob(self.mount, ['**/file']))
        self.assertEqual(
            ['adir/file'], self.client.glob(self.mount, ['adir/*']))
        self.assertCountEqual(
            ['adir/file', 'bdir/file'],
            self.client.glob(self.mount, ['adir/*', '**/file']),
            msg='De-duplicate results from multiple globs')
        self.assertEqual(
            ['hello'], self.client.glob(self.mount, ['hello']))
        self.assertEqual(
            [], self.client.glob(self.mount, ['hell']),
            msg="No accidental substring match")
        self.assertEqual(
            ['hello'], self.client.glob(self.mount, ['hel*']))
        self.assertEqual(
            ['adir'], self.client.glob(self.mount, ['ad*']))
        self.assertEqual(
            ['adir/file'], self.client.glob(self.mount, ['adir/**/*']))
        self.assertEqual(
            ['adir/file'], self.client.glob(self.mount, ['adir/**']))

        with self.assertRaises(EdenError) as ctx:
            self.client.glob(self.mount, ['adir['])
        self.assertIn('unterminated bracket sequence',
                      str(ctx.exception))

    def test_unload_free_inodes(self):
        for i in range(100):
            self.write_file('testfile%d.txt' % i, 'unload test case')

        inode_count_before_unload = self.get_loaded_inodes_count('')
        self.assertGreater(
            inode_count_before_unload, 100,
            'Number of loaded inodes should increase'
        )

        age = TimeSpec()
        age.seconds = 0
        age.nanoSeconds = 0
        unload_count = self.client.unloadInodeForPath(self.mount, '', age)

        self.assertGreaterEqual(
            unload_count, 100,
            'Number of loaded inodes should reduce after unload'
        )

    # Checks if unloadInodeForPath unloads inodes based on the age
    def test_unload_free_inodes_age(self):
        age_to_unload = 10
        old_timestamp = time.time() - (age_to_unload * 2)

        # Load 100 inodes and set their atime to a very old value.
        for i in range(100):
            filename = os.path.join(self.mount, 'testfile_old%d.txt' % i)
            self.write_file(filename, 'unload test case')
            os.utime(filename, (old_timestamp, old_timestamp))

        # Load another 100 inodes whose atime is close to current time.
        for i in range(100):
            self.write_file('testfile_new%d.txt' % i, 'unload test case')

        inode_count_before_unload = self.get_loaded_inodes_count('')
        self.assertGreater(
            inode_count_before_unload, 200, 'Number of loaded inodes should increase'
        )
        age = TimeSpec()
        age.seconds = age_to_unload
        age.nanoSeconds = 0
        unloaded_inode_count = self.client.unloadInodeForPath(self.mount, '', age)
        result = self.client.debugInodeStatus(self.mount, '')

        # Check if the inodes we are epecting to be unloaded are actually unloading.
        for item in result:
            for inode in item.entries:
                if inode.loaded:
                    # If a file is loaded check that it is not old file (not all the
                    # ones that are loaded are new files, there can be other files too).
                    self.assertFalse(
                        str(inode.name).find('testfile_old') != -1,
                        'old inodes should not be loaded'
                    )
                else:
                    # check that the inodes that are unloaded are not the new ones
                    # (not all the files that are unloaded are new ones).
                    self.assertFalse(
                        str(inode.name).find('testfile_new') != -1,
                        'new inodes should not be unloaded'
                    )

        self.assertEqual(
            unloaded_inode_count, 100, 'Only the old batch of inodes should unload'
        )

    def read_file(self, filename):
        with open(filename, 'r') as f:
            f.read()

    def get_counter(self, name):
        self.client.flushStatsNow()
        return self.client.getCounters()[name]

    def test_invalidate_inode_cache(self):
        filename = os.path.join(self.mount, 'bdir/file')
        dirname = os.path.join(self.mount, 'bdir/')

#       Exercise eden a bit to make sure counters are ready
        for _ in range(20):
            fn = os.path.join(self.mount, '_tmp_')
            with open(fn, 'w') as f:
                f.write('foo!\n')
            os.unlink(fn)

        reads = self.get_counter("fuse.read_us.count")
        self.read_file(filename)
        reads_1read = self.get_counter("fuse.read_us.count")
        self.assertEqual(reads_1read, reads + 1)
        self.read_file(filename)
        reads_2read = self.get_counter("fuse.read_us.count")
        self.assertEqual(reads_1read, reads_2read)
        self.client.invalidateKernelInodeCache(self.mount, 'bdir/file')
        self.read_file(filename)
        reads_3read = self.get_counter("fuse.read_us.count")
        self.assertEqual(reads_2read + 1, reads_3read)

        lookups = self.get_counter("fuse.lookup_us.count")
#        -hl makes ls to do a lookup of the file to determine type
        os.system("ls -hl " + dirname + " > /dev/null")
        lookups_1ls = self.get_counter("fuse.lookup_us.count")
#        equal, the file was lookup'ed above.
        self.assertEqual(lookups, lookups_1ls)
        self.client.invalidateKernelInodeCache(self.mount, 'bdir')
        os.system("ls -hl " + dirname + " > /dev/null")
        lookups_2ls = self.get_counter("fuse.lookup_us.count")
        self.assertEqual(lookups_1ls + 1, lookups_2ls)
