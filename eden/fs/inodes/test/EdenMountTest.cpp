/*
 *  Copyright (c) 2004-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#include "eden/fs/inodes/EdenMount.h"

#include <folly/Range.h>
#include <folly/test/TestUtils.h>
#include <folly/chrono/Conv.h>
#include <gtest/gtest.h>

#include "eden/fs/config/ClientConfig.h"
#include "eden/fs/inodes/TreeInode.h"
#include "eden/fs/journal/Journal.h"
#include "eden/fs/journal/JournalDelta.h"
#include "eden/fs/testharness/FakeBackingStore.h"
#include "eden/fs/testharness/FakeTreeBuilder.h"
#include "eden/fs/testharness/TestChecks.h"
#include "eden/fs/testharness/TestMount.h"
#include "eden/fs/testharness/TestUtil.h"

using folly::Optional;

namespace facebook {
namespace eden {

TEST(EdenMount, initFailure) {
  // Test initializing an EdenMount with a commit hash that does not exist.
  // This should fail with an exception, and not crash.
  TestMount testMount;
  EXPECT_THROW_RE(
      testMount.initialize(makeTestHash("1")),
      std::domain_error,
      "commit 0{39}1 not found");
}

TEST(EdenMount, resetParents) {
  TestMount testMount;

  // Prepare two commits
  auto builder1 = FakeTreeBuilder();
  builder1.setFile("src/main.c", "int main() { return 0; }\n");
  builder1.setFile("src/test.c", "testy tests");
  builder1.setFile("doc/readme.txt", "all the words");
  builder1.finalize(testMount.getBackingStore(), true);
  auto commit1 = testMount.getBackingStore()->putCommit("1", builder1);
  commit1->setReady();

  auto builder2 = builder1.clone();
  builder2.replaceFile("src/test.c", "even more testy tests");
  builder2.setFile("src/extra.h", "extra stuff");
  builder2.finalize(testMount.getBackingStore(), true);
  auto commit2 = testMount.getBackingStore()->putCommit("2", builder2);
  commit2->setReady();

  // Initialize the TestMount pointing at commit1
  testMount.initialize(makeTestHash("1"));
  const auto& edenMount = testMount.getEdenMount();
  EXPECT_EQ(ParentCommits{makeTestHash("1")}, edenMount->getParentCommits());
  EXPECT_EQ(
      ParentCommits{makeTestHash("1")},
      edenMount->getConfig()->getParentCommits());
  auto latestJournalEntry = edenMount->getJournal().getLatest();
  EXPECT_EQ(makeTestHash("1"), latestJournalEntry->fromHash);
  EXPECT_EQ(makeTestHash("1"), latestJournalEntry->toHash);
  EXPECT_FILE_INODE(testMount.getFileInode("src/test.c"), "testy tests", 0644);
  EXPECT_FALSE(testMount.hasFileAt("src/extra.h"));

  // Reset the TestMount to pointing to commit2
  edenMount->resetParent(makeTestHash("2"));
  // The snapshot ID should be updated, both in memory and on disk
  EXPECT_EQ(ParentCommits{makeTestHash("2")}, edenMount->getParentCommits());
  EXPECT_EQ(
      ParentCommits{makeTestHash("2")},
      edenMount->getConfig()->getParentCommits());
  latestJournalEntry = edenMount->getJournal().getLatest();
  EXPECT_EQ(makeTestHash("1"), latestJournalEntry->fromHash);
  EXPECT_EQ(makeTestHash("2"), latestJournalEntry->toHash);
  // The file contents should not have changed.
  // Even though we are pointing at commit2, the working directory contents
  // still look like commit1.
  EXPECT_FILE_INODE(testMount.getFileInode("src/test.c"), "testy tests", 0644);
  EXPECT_FALSE(testMount.hasFileAt("src/extra.h"));
}

// Tests if last checkout time is getting updated correctly or not.
TEST(EdenMount, testLastCheckoutTime) {
  TestMount testMount;

  auto builder = FakeTreeBuilder();
  builder.setFile("dir/foo.txt", "Fooooo!!");
  builder.finalize(testMount.getBackingStore(), true);
  auto commit = testMount.getBackingStore()->putCommit("1", builder);
  commit->setReady();

  auto sec = std::chrono::seconds{50000};
  auto nsec = std::chrono::nanoseconds{10000};
  auto duration = sec + nsec;
  std::chrono::system_clock::time_point currentTime(
      std::chrono::duration_cast<std::chrono::system_clock::duration>(
          duration));

  testMount.initialize(makeTestHash("1"), currentTime);
  const auto& edenMount = testMount.getEdenMount();
  struct timespec lastCheckoutTime = edenMount->getLastCheckoutTime();

  // Check if EdenMount is updating lastCheckoutTime correctly
  EXPECT_EQ(sec.count(), lastCheckoutTime.tv_sec);
  EXPECT_EQ(nsec.count(), lastCheckoutTime.tv_nsec);

  // Check if FileInode is updating lastCheckoutTime correctly
  auto fileInode = testMount.getFileInode("dir/foo.txt");
  auto stFile = fileInode->getTimestamps();
  EXPECT_EQ(sec.count(), stFile.atime.tv_sec);
  EXPECT_EQ(nsec.count(), stFile.atime.tv_nsec);
  EXPECT_EQ(sec.count(), stFile.ctime.tv_sec);
  EXPECT_EQ(nsec.count(), stFile.ctime.tv_nsec);
  EXPECT_EQ(sec.count(), stFile.mtime.tv_sec);
  EXPECT_EQ(nsec.count(), stFile.mtime.tv_nsec);

  // Check if TreeInode is updating lastCheckoutTime correctly
  auto treeInode = testMount.getTreeInode("dir");
  InodeBase::InodeTimestamps stDir = treeInode->getTimestamps();
  EXPECT_EQ(sec.count(), stDir.atime.tv_sec);
  EXPECT_EQ(nsec.count(), stDir.atime.tv_nsec);
  EXPECT_EQ(sec.count(), stDir.ctime.tv_sec);
  EXPECT_EQ(nsec.count(), stDir.ctime.tv_nsec);
  EXPECT_EQ(sec.count(), stDir.mtime.tv_sec);
  EXPECT_EQ(nsec.count(), stDir.mtime.tv_nsec);
}

TEST(EdenMount, testCreatingFileSetsTimestampsToNow) {
  TestMount testMount;

  auto builder = FakeTreeBuilder();
  builder.setFile("initial/file.txt", "was here");
  builder.finalize(testMount.getBackingStore(), true);
  auto commit = testMount.getBackingStore()->putCommit("1", builder);
  commit->setReady();

  auto& clock = testMount.getClock();

  auto lastCheckoutTime = clock.getTimePoint();

  testMount.initialize(makeTestHash("1"), lastCheckoutTime);

  using namespace std::literals::chrono_literals;
  clock.advance(10min);

  auto newFile = testMount.getEdenMount()
                     ->getRootInode()
                     ->create(PathComponentPiece{"newfile.txt"}, 0660, 0)
                     .get();
  auto fileInode = testMount.getFileInode("newfile.txt");
  auto timestamps = fileInode->getTimestamps();
  EXPECT_EQ(
      clock.getTimePoint(), folly::to<FakeClock::time_point>(timestamps.atime));
  EXPECT_EQ(
      clock.getTimePoint(), folly::to<FakeClock::time_point>(timestamps.ctime));
  EXPECT_EQ(
      clock.getTimePoint(), folly::to<FakeClock::time_point>(timestamps.mtime));
}
} // namespace eden
} // namespace facebook
