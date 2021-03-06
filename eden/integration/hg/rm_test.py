#!/usr/bin/env python3
#
# Copyright (c) 2016-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import os

from .lib.hg_extension_test_base import EdenHgTestCase, hg_test
from ..lib import hgrepo


@hg_test
class RmTest(EdenHgTestCase):
    def populate_backing_repo(self, repo):
        repo.write_file('apple', '')
        repo.write_file('banana', '')
        repo.commit('first commit')

    def test_rm_file(self):
        self.hg('rm', 'apple')
        self.assert_status({'apple': 'R'})
        self.assertFalse(os.path.isfile(self.get_path('apple')))
        self.assertTrue(os.path.isfile(self.get_path('banana')))

    def test_rm_modified_file(self):
        self.write_file('apple', 'new contents')

        with self.assertRaises(hgrepo.HgError) as context:
            self.hg('rm', 'apple')
        expected_msg = (
            'not removing apple: '
            'file is modified (use -f to force removal)'
        )
        self.assertIn(expected_msg, str(context.exception))
        self.assert_status({'apple': 'M'})

        self.hg('rm', '--force', 'apple')
        self.assert_status({'apple': 'R'})
        self.assertFalse(os.path.isfile(self.get_path('apple')))
        self.assertTrue(os.path.isfile(self.get_path('banana')))

    def test_rm_modified_file_permissions(self):
        os.chmod(self.get_path('apple'), 0o755)

        with self.assertRaises(hgrepo.HgError) as context:
            self.hg('rm', 'apple')
        expected_msg = (
            'not removing apple: '
            'file is modified (use -f to force removal)'
        )
        self.assertIn(expected_msg, str(context.exception))
        self.assert_status({'apple': 'M'})

        self.hg('rm', '--force', 'apple')
        self.assert_status({'apple': 'R'})
        self.assertFalse(os.path.isfile(self.get_path('apple')))
        self.assertTrue(os.path.isfile(self.get_path('banana')))

    def test_rm_directory(self):
        self.mkdir('dir')
        self.touch('dir/1')
        self.touch('dir/2')
        self.touch('dir/3')
        self.hg('add')
        self.repo.commit('second commit')

        self.hg('rm', 'dir')
        self.assert_status({'dir/1': 'R', 'dir/2': 'R', 'dir/3': 'R'})
        self.assertFalse(os.path.exists(self.get_path('dir')))

    def test_rm_directory_with_modification(self):
        self.mkdir('dir')
        self.touch('dir/1')
        self.touch('dir/2')
        self.touch('dir/3')
        self.hg('add')
        self.repo.commit('second commit')

        self.write_file('dir/2', 'new contents')
        self.assert_status({'dir/2': 'M'})

        with self.assertRaises(hgrepo.HgError) as context:
            self.hg('rm', 'dir')
        expected_msg = (
            'not removing dir/2: '
            'file is modified (use -f to force removal)'
        )
        self.assertIn(expected_msg, str(context.exception))
        self.assert_status({'dir/1': 'R', 'dir/2': 'M', 'dir/3': 'R'})
        self.assertFalse(os.path.exists(self.get_path('dir/1')))
        self.assertTrue(os.path.exists(self.get_path('dir/2')))
        self.assertFalse(os.path.exists(self.get_path('dir/3')))
