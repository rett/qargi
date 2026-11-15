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

The build checks recognized `qargi` examples in inline code and supported shell fences against the release's command descriptions. It checks command and verb names and recognized options. It does not execute examples, validate every argument or check all prose as commands. The generated reference comes from those same descriptions, so these checks cannot independently establish implementation behavior.

Internal links and anchors must resolve, and the build checks forbidden names and the generated output's structure. Structural output checking provides no independent visual review or deployed-site verification. Read the plan a command prints before applying it and verify the advice against your project's requirements.

The examples use these names: the project `myproject`, the members `forge`, `scribe` and `reader`, and the run slug `rename-verb`. Words in capitals such as `NAME`, `RUN` and `TOKEN` stand for a value you supply.

## 5. Which release a page describes

The header and the footer of each page name the release it was checked against. When the hand pages are ahead of a release the stamp says so. If you run an older qargi than the stamp, `qargi version` tells you which one you have, and the [releases](/releases/) page tells you what differs.

Commands introduced after that release wait for a source and site-version update. Before publishing a new release, the lead builds against its actual source, inspects the layout and independently reviews the source. Publication requires its own approval.

## 6. Report a problem

Open an issue at [github.com/rett/qargi/issues](https://github.com/rett/qargi/issues). Say which page, what you typed or read, what you expected and what happened, and the output of `qargi version`. For a problem with a command, include its exit status and the message. Do not paste tokens, credentials or private paths.

## 7. See also

- [Home](/)
- [Safety](/safety/)
- [Releases](/releases/)
- [Command reference](/reference/)
