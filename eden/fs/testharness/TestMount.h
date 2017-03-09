/*
 *  Copyright (c) 2016-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#pragma once

#include <folly/Range.h>
#include <folly/experimental/TestUtil.h>
#include <sys/stat.h>
#include <vector>
#include "eden/fs/inodes/Dirstate.h"
#include "eden/fs/inodes/DirstatePersistence.h"
#include "eden/fs/inodes/EdenMount.h"
#include "eden/fs/inodes/InodePtr.h"
#include "eden/fs/inodes/gen-cpp2/overlay_types.h"
#include "eden/fs/model/TreeEntry.h"
#include "eden/utils/PathFuncs.h"

namespace facebook {
namespace eden {
class ClientConfig;
class FakeBackingStore;
class FakeTreeBuilder;
class FileInode;
class LocalStore;
class TreeInode;
template <typename T>
class StoredObject;
using StoredHash = StoredObject<Hash>;

struct TestMountFile {
  RelativePath path;
  std::string contents;
  uint8_t rwx = 0b110;
  FileType type = FileType::REGULAR_FILE;

  /** Performs a structural equals comparison. */
  bool operator==(const TestMountFile& other) const;

  /**
   * @param p is a StringPiece (rather than a RelativePath) for convenience
   *     for creating instances of TestMountFile for unit tests.
   */
  TestMountFile(folly::StringPiece p, folly::StringPiece c)
      : path(p), contents(c.str()) {}
};

class TestMount {
 public:
  /**
   * Create a new uninitialized TestMount.
   *
   * The TestMount will not be fully initialized yet.  The caller must
   * populate the object store as desired, and then call initialize() to
   * create the underlying EdenMount object once the commit has been set up.
   */
  TestMount();

  /**
   * Create a new TestMount
   *
   * If startReady is true, all of the Tree and Blob objects created by the
   * rootBuilder will be made immediately ready in the FakeBackingStore.  If
   * startReady is false the objects will not be ready, and attempts to
   * retrieve them from the backing store will not complete until the caller
   * explicitly marks them ready.
   *
   * However, the root Tree object is always marked ready.  This is necessary
   * to create the EdenMount object.
   *
   * If an initialCommitHash is not explicitly specified, makeTestHash("1")
   * will be used.
   */
  explicit TestMount(FakeTreeBuilder& rootBuilder, bool startReady = true);
  TestMount(
      Hash initialCommitHash,
      FakeTreeBuilder& rootBuilder,
      bool startReady = true);

  ~TestMount();

  /**
   * Initialize the mount.
   *
   * This should only be used if the TestMount was default-constructed.
   * The caller must have already defined the root commit.
   */
  void initialize(Hash initialCommitHash);

  /**
   * Initialize the mount.
   *
   * This should only be used if the TestMount was default-constructed.
   * The caller must have already defined the root Tree in the object store.
   */
  void initialize(Hash initialCommitHash, Hash rootTreeHash);

  /**
   * Initialize the mount from the given root tree.
   *
   * This should only be used if the TestMount was default-constructed.
   *
   * If an initialCommitHash is not explicitly specified, makeTestHash("1")
   * will be used.
   */
  void initialize(
      Hash initialCommitHash,
      FakeTreeBuilder& rootBuilder,
      bool startReady = true);
  void initialize(FakeTreeBuilder& rootBuilder, bool startReady = true);

  /**
   * Set the initial directives stored in the on-disk dirstate.
   *
   * This method should only be called before initialize().  This allows tests
   * to imitate mounting an existing eden client that has saved dirstate
   * information.
   */
  void setInitialDirstate(
      const std::unordered_map<RelativePath, overlay::UserStatusDirective>&
          userDirectives);

  /**
   * Get the ClientConfig object.
   *
   * The ClientConfig object provides methods to get the paths to the mount
   * point, the client directory, etc.
   */
  ClientConfig* getConfig() const {
    return config_.get();
  }

  /**
   * Get the LocalStore.
   *
   * Callers can use this to populate the LocalStore before calling build().
   */
  const std::shared_ptr<LocalStore>& getLocalStore() const {
    return localStore_;
  }

  /**
   * Get the LocalStore.
   *
   * Callers can use this to populate the BackingStore before calling build().
   */
  const std::shared_ptr<FakeBackingStore>& getBackingStore() const {
    return backingStore_;
  }

  /**
   * Add file to the mount; it will be available in the overlay.
   */
  void addFile(folly::StringPiece path, folly::StringPiece contents);

  void mkdir(folly::StringPiece path);

  /** Overwrites the contents of an existing file. */
  void overwriteFile(folly::StringPiece path, std::string contents);

  std::string readFile(folly::StringPiece path);

  /** Returns true if path identifies a regular file in the tree. */
  bool hasFileAt(folly::StringPiece path);

  void deleteFile(folly::StringPiece path);
  void rmdir(folly::StringPiece path);

  InodePtr getInode(RelativePathPiece path) const;
  InodePtr getInode(folly::StringPiece path) const;
  TreeInodePtr getTreeInode(RelativePathPiece path) const;
  TreeInodePtr getTreeInode(folly::StringPiece path) const;
  FileInodePtr getFileInode(RelativePathPiece path) const;
  FileInodePtr getFileInode(folly::StringPiece path) const;

  /** Convenience method for getting the Tree for the root of the mount. */
  std::unique_ptr<Tree> getRootTree() const;

  const std::shared_ptr<EdenMount>& getEdenMount() const {
    return edenMount_;
  }

  Dirstate* getDirstate() const;

 private:
  void initTestDirectory();
  void setInitialCommit(Hash commitHash);
  void setInitialCommit(Hash commitHash, Hash rootTreeHash);

  /**
   * The temporary directory for this TestMount.
   *
   * This must be stored as a member variable to ensure the temporary directory
   * lives for the duration of the test.
   *
   * We intentionally list it before the edenMount_ so it gets constructed
   * first, and destroyed (and deleted from disk) after the EdenMount is
   * destroyed.
   */
  std::unique_ptr<folly::test::TemporaryDirectory> testDir_;

  std::shared_ptr<EdenMount> edenMount_;
  std::shared_ptr<LocalStore> localStore_;
  std::shared_ptr<FakeBackingStore> backingStore_;
  /*
   * config_ is only set before edenMount_ has been initialized.
   * When edenMount_ is created we pass ownership of the config to edenMount_.
   */
  std::unique_ptr<ClientConfig> config_;
};
}
}
