/*
 *  Copyright (c) 2016-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */

#include <folly/Conv.h>
#include <folly/experimental/FunctionScheduler.h>
#include <folly/experimental/logging/Init.h>
#include <folly/experimental/logging/xlog.h>
#include <folly/init/Init.h>
#include <gflags/gflags.h>
#include <pwd.h>
#include <sysexits.h>
#include "EdenServer.h"
#include "eden/fs/fuse/privhelper/PrivHelper.h"
#include "eden/fs/fuse/privhelper/UserInfo.h"

DEFINE_bool(allowRoot, false, "Allow running eden directly as root");
DEFINE_string(edenDir, "", "The path to the .eden directory");
DEFINE_string(
    etcEdenDir,
    "/etc/eden",
    "The directory holding all system configuration files");
DEFINE_string(configPath, "", "The path of the ~/.edenrc config file");
DEFINE_string(rocksPath, "", "The path to the local RocksDB store");

// The logging configuration parameter.  We default to DBG2 for everything in
// eden, and WARNING for all other categories.
DEFINE_string(logging, ".=WARNING,eden=DBG2", "Logging configuration");

using namespace facebook::eden::fusell;
using namespace facebook::eden;

int main(int argc, char** argv) {
  // Make sure to run this before any flag values are read.
  folly::init(&argc, &argv);

  // Determine the desired user and group ID.
  if (geteuid() != 0) {
    fprintf(stderr, "error: edenfs must be started as root\n");
    return EX_NOPERM;
  }

  auto identity = UserInfo::lookup();
  if (identity.getUid() == 0 && !FLAGS_allowRoot) {
    fprintf(
        stderr,
        "error: you appear to be running eden as root, "
        "rather than using\n"
        "sudo or a setuid binary.  This is normally undesirable.\n"
        "Pass in the --allowRoot flag if you really mean to run "
        "eden as root.\n");
    return EX_USAGE;
  }

  // Set some default glog settings, to be applied unless overridden on the
  // command line
  gflags::SetCommandLineOptionWithMode(
      "logtostderr", "1", gflags::SET_FLAGS_DEFAULT);
  gflags::SetCommandLineOptionWithMode(
      "minloglevel", "0", gflags::SET_FLAGS_DEFAULT);

  // Fork the privhelper process, then drop privileges in the main process.
  // This should be done as early as possible, so that everything else we do
  // runs only with normal user privileges.
  //
  // (It might be better to do this even before calling folly::init() and
  // parsing command line arguments.  The downside would be that we then
  // shouldn't really use glog in the privhelper process, since it won't have
  // been set up and configured based on the command line flags.)
  fusell::startPrivHelper(identity);
  identity.dropPrivileges();

  folly::initLogging(FLAGS_logging);

  XLOG(INFO) << "Starting edenfs.  UID=" << identity.getUid()
             << ", GID=" << identity.getGid() << ", PID=" << getpid();

  if (FLAGS_edenDir.empty()) {
    fprintf(stderr, "error: the --edenDir argument is required\n");
    return EX_USAGE;
  }
  auto edenDir = canonicalPath(FLAGS_edenDir);
  auto etcEdenDir = canonicalPath(FLAGS_etcEdenDir);
  auto rocksPath = FLAGS_rocksPath.empty()
      ? edenDir + RelativePathPiece{"storage/rocks-db"}
      : canonicalPath(FLAGS_rocksPath);

  AbsolutePath configPath;
  std::string configPathStr = FLAGS_configPath;
  if (configPathStr.empty()) {
    configPath = identity.getHomeDirectory() + PathComponentPiece{".edenrc"};
  } else {
    configPath = canonicalPath(configPathStr);
  }

  EdenServer server(edenDir, etcEdenDir, configPath, rocksPath);
  server.run();
  return EX_OK;
}
