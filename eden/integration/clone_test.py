#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

from .lib import edenclient, testcase
from textwrap import dedent
import errno
import os
import subprocess
import stat
import tempfile


# This is the name of the default repository created by EdenRepoTestBase.
repo_name = 'main'


@testcase.eden_repo_test
class CloneTest:
    def populate_repo(self):
        self.repo.write_file('hello', 'hola\n')
        self.repo.commit('Initial commit.')

    def test_clone_to_non_existent_directory(self):
        tmp = self._new_tmp_dir()
        non_existent_dir = os.path.join(tmp, 'foo/bar/baz')

        self.eden.run_cmd('clone', repo_name, non_existent_dir)
        self.assertTrue(os.path.isfile(os.path.join(non_existent_dir, 'hello')),
                        msg='clone should succeed in non-existent directory')

    def test_clone_to_existing_empty_directory(self):
        tmp = self._new_tmp_dir()
        empty_dir = os.path.join(tmp, 'foo/bar/baz')
        os.makedirs(empty_dir)

        self.eden.run_cmd('clone', repo_name, empty_dir)
        self.assertTrue(os.path.isfile(os.path.join(empty_dir, 'hello')),
                        msg='clone should succeed in empty directory')

    def test_clone_from_repo(self):
        # Specify the source of the clone as an existing local repo rather than
        # an alias for a config.
        destination_dir = self._new_tmp_dir()
        self.eden.run_cmd('clone', self.repo.path, destination_dir)
        self.assertTrue(os.path.isfile(os.path.join(destination_dir, 'hello')),
                        msg='clone should succeed in empty directory')

    def test_clone_from_eden_repo(self):
        # Add a config alias for a repo with some bind mounts.
        edenrc = os.path.join(os.environ['HOME'], '.edenrc')
        with open(edenrc, 'w') as f:
            f.write(
                dedent(
                    f'''\
            [repository {repo_name}]
            path = {self.repo.get_canonical_root()}
            type = {self.repo.get_type()}

            [bindmounts {repo_name}]
            bm1 = tmp/bm1
            bm2 = tmp/bm2
            '''
                )
            )

        # Create an Eden mount from the config alias.
        eden_clone1 = self._new_tmp_dir()
        self.eden.run_cmd('clone', repo_name, eden_clone1)
        self.assertTrue(os.path.isdir(os.path.join(eden_clone1, 'tmp/bm1')),
                        msg='clone should create bind mount')

        # Clone the Eden clone! Note it should inherit its config.
        eden_clone2 = self._new_tmp_dir()
        self.eden.run_cmd('clone', '--snapshot', self.repo.get_head_hash(),
                          eden_clone1, eden_clone2)
        self.assertTrue(os.path.isdir(os.path.join(eden_clone2, 'tmp/bm1')),
                        msg='clone should inherit its config from eden_clone1, '
                            'which should include the bind mounts.')

    def test_clone_to_non_empty_directory_fails(self):
        tmp = self._new_tmp_dir()
        non_empty_dir = os.path.join(tmp, 'foo/bar/baz')
        os.makedirs(non_empty_dir)
        with open(os.path.join(non_empty_dir, 'example.txt'), 'w') as f:
            f.write('I am not empty.\n')

        with self.assertRaises(subprocess.CalledProcessError) as context:
            self.eden.run_cmd('clone', repo_name, non_empty_dir)
        stderr = context.exception.stderr.decode('utf-8')
        self.assertIn(os.strerror(errno.ENOTEMPTY), stderr,
                      msg='clone into non-empty dir should raise ENOTEMPTY')

    def test_clone_to_file_fails(self):
        tmp = self._new_tmp_dir()
        non_empty_dir = os.path.join(tmp, 'foo/bar/baz')
        os.makedirs(non_empty_dir)
        file_in_directory = os.path.join(non_empty_dir, 'example.txt')
        with open(file_in_directory, 'w') as f:
            f.write('I am not empty.\n')

        with self.assertRaises(subprocess.CalledProcessError) as context:
            self.eden.run_cmd('clone', repo_name, file_in_directory)
        stderr = context.exception.stderr.decode('utf-8')
        self.assertIn(os.strerror(errno.ENOTDIR), stderr,
                      msg='clone into file should raise ENOTDIR')

    def test_clone_to_non_existent_directory_that_is_under_a_file_fails(self):
        tmp = self._new_tmp_dir()
        non_existent_dir = os.path.join(tmp, 'foo/bar/baz')
        with open(os.path.join(tmp, 'foo'), 'w') as f:
            f.write('I am not empty.\n')

        with self.assertRaises(subprocess.CalledProcessError) as context:
            self.eden.run_cmd('clone', repo_name, non_existent_dir)
        stderr = context.exception.stderr.decode('utf-8')
        self.assertIn(os.strerror(errno.ENOTDIR), stderr,
                      msg='When the directory cannot be created because the '
                          'ancestor is a parent, clone should raise ENOTDIR')

    def test_post_clone_hook(self):
        edenrc = os.path.join(os.environ['HOME'], '.edenrc')
        hooks_dir = os.path.join(self.tmp_dir, 'the_hooks')
        os.mkdir(hooks_dir)

        with open(edenrc, 'w') as f:
            f.write('''\
[repository {repo_name}]
path = {repo_path}
type = {repo_type}
hooks = {hooks_dir}
'''.format(repo_name=repo_name,
             repo_path=self.repo.get_canonical_root(),
             repo_type=self.repo.get_type(),
             hooks_dir=hooks_dir))

        # Create a post-clone hook that has a visible side-effect every time it
        # is run so we can verify that it is only run once.
        hg_post_clone_hook = os.path.join(hooks_dir, 'post-clone')
        scratch_file = os.path.join(self.tmp_dir, 'scratch_file')
        with open(scratch_file, 'w') as f:
            f.write('ok')
        with open(hg_post_clone_hook, 'w') as f:
            f.write('''\
#!/bin/bash
CONTENTS=`cat "{scratch_file}"`
echo -n "$1" >> "{scratch_file}"
'''.format(scratch_file=scratch_file))
        os.chmod(hg_post_clone_hook, stat.S_IRWXU)

        # Verify that the hook gets run as part of `eden clone`.
        self.assertEqual('ok', _read_all(scratch_file))
        tmp = self._new_tmp_dir()
        self.eden.clone(repo_name, tmp)
        new_contents = 'ok' + self.repo.get_type()
        self.assertEqual(new_contents, _read_all(scratch_file))

        # Restart Eden and verify that post-clone is NOT run again.
        self.eden.shutdown()
        self.eden.start()
        self.assertEqual(new_contents, _read_all(scratch_file))

    def test_attempt_clone_invalid_repo_name(self):
        tmp = self._new_tmp_dir()
        repo_name = 'repo-name-that-is-not-in-the-config'

        with self.assertRaises(edenclient.EdenCommandError) as context:
            self.eden.run_cmd('clone', repo_name, tmp)
        self.assertIn(
            f'No repository configured named "{repo_name}". '
            'Try one of: "main".', context.exception.stderr.decode())

    def test_clone_should_start_daemon(self):
        # Shut down Eden.
        self.assertTrue(self.eden.is_healthy())
        self.eden.shutdown()
        self.assertFalse(self.eden.is_healthy())

        # Check `eden list`.
        expected_list_output = f'{self.mount}\n'
        list_output = self.eden.list_cmd()
        self.assertEqual(expected_list_output, list_output,
                         msg='Eden should have one mount.')

        # Verify that clone starts the daemon.
        tmp = self._new_tmp_dir()
        self.eden.run_cmd('clone', self.repo.path, tmp)
        self.assertTrue(self.eden.is_healthy(), msg='clone should start Eden.')
        mount_points = '\n'.join(sorted([self.mount, tmp])) + '\n'
        self.assertEqual(mount_points, self.eden.list_cmd(),
                         msg='Eden should have two mounts.')
        self.assertEqual('hola\n', _read_all(os.path.join(tmp, 'hello')))

    def _new_tmp_dir(self):
        return tempfile.mkdtemp(dir=self.tmp_dir)


def _read_all(path):
    '''One-liner to read the contents of a file and properly close the fd.'''
    with open(path, 'r') as f:
        return f.read()
