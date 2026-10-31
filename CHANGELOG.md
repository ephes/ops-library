# Changelog

## [Unreleased]



- Fix the OpenClaw todo skill instructions to dispatch scheduled `/todo reminder`
  to the handler’s top-level `reminder` command. The previous `todo reminder`
  invocation failed and eventually caused automatic scheduler disablement.

