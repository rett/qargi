---
title: About these docs
description: The licence, the alpha status, what these pages cover and how they are checked, how to see which release they describe and how to report a problem.
doctype: explanation
---
## 1. Licence

qargi is released under the MIT licence. The text is in the `LICENSE` file of the [repository](https://github.com/rett/qargi). The licence applies to the tool and to these pages.

## 2. Status

qargi is alpha. It is versioned with Semantic Versioning and is below 1.0, so a command, an option or a file format can change in any release. The [releases](/releases/) page lists every change, and the Changed and Removed sections are the ones to read before you update. Expect rough edges and report them.

## 3. What is here and what is not

- The pages written by hand cover the work of a lead: install, set up, the daily loop, dispatching and verifying a task, and safety.
- The [command reference](/reference/) is generated from the same description that `qargi help` and `man qargi` print, for the release named in the header and footer of every page.
- The [releases](/releases/) page is generated from the changelog.
- The README in the repository is the overview, and `man qargi` is the complete manual. These pages do not repeat them.

## 4. How the pages are checked

Every `qargi` command and option that a page names is looked up in the command description of the release. Links and anchors must resolve. A page that names a command that does not exist, or a private name from the list of forbidden words, fails the build and is not published. The check proves that a command exists and takes that option; it does not prove that the advice is right for your project, so read the plan a command prints before you apply it.

The examples use these names: the project `myproject`, the members `forge`, `scribe` and `reader`, and the run slug `rename-verb`. Words in capitals such as `NAME`, `RUN` and `TOKEN` stand for a value you supply.

## 5. Which release a page describes

The header and the footer of each page name the release it was checked against. When the hand pages are ahead of a release the stamp says so. If you run an older qargi than the stamp, `qargi version` tells you which one you have, and the [releases](/releases/) page tells you what differs.

## 6. Report a problem

Open an issue at [github.com/rett/qargi/issues](https://github.com/rett/qargi/issues). Say which page, what you typed or read, what you expected and what happened, and the output of `qargi version`. For a problem with a command, include its exit status and the message. Do not paste tokens, credentials or private paths.

## 7. See also

- [Home](/)
- [Safety](/safety/)
- [Releases](/releases/)
- [Command reference](/reference/)
