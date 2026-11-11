#!/usr/bin/env python3
"""The MCP tools of a role: which tools of its tool packs a role gets, what a runtime calls each of them, and whether a member may call one.

One answer for the three places that need it:
  lib/packs_render.py   a permission rule of the render names a tool as the runtime does (part)
  lib/agent.sh          the tool list of a member holds the MCP tools its roles may call, and none when no tool pack reaches them (member_tools)
  lib/guard.py          a member's call of an MCP tool is judged by the policy the role's packs give that tool (refusal)

What a runtime calls a tool is data of its definition (lib/providers/NAME.json, resources.mcp): permission_rule is the form of the name, with
{server} for the name of the tool pack and {tool} for the tool (mcp__{server}__{tool}, say); name_key is how the runtime writes each of the
two inside it (nonword-underscore: every character that is not an ASCII letter, a digit, _ or - becomes _, so under that rule the tool
platform.list_items of the pack kb is mcp__kb__platform_list_items; absent or null: as written). Two tools of a role that get the same name this way cannot be told apart,
so neither is given to a member and a call of the name is refused.

The packs of a role are the ones `qargi tool effective PROJECT ROLE` lists for the local surface: every tool pack linked at a scope that reaches the
role, minus the role's packs_off, minus a pack the project's local runtime cannot use. A pack counts only as it was approved: one that is missing,
changed since its approval or fails its review gives no tool.

A call is allowed when the tool is in such a pack and
  - its policy is not always_ask (that tool waits for a person's answer, and a member runs unattended), and
  - under the read-only class, it is a declared read: its policy is always_allow, its name is not write-like (lib/packs_check.py write_like) and,
    when the pack was approved with the server's tool listing (tool import|seal --tool-list), the listing marks it readOnlyHint true.

Stdlib only; lib/packs_check.py (the review, the content hash, the one definition of a write-like name) is loaded when a pack is read."""
import collections
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NAME_KEYS = {"nonword-underscore": (re.compile(r"[^A-Za-z0-9_-]"), "_")}       # name_key of resources.mcp: (the characters the runtime does not keep, what it writes for each)
PLACEHOLDER = re.compile(r"\{(server|tool)\}")
PACK_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}\Z")
SCOPES = ("user", "user-role", "project", "project-role")

Tool = collections.namedtuple("Tool", "pack tool policy read why_not_read unusable")   # one tool of a role's packs; unusable: why the pack gives no tool, or None


class McpError(Exception):
    """The links, the answers or a pack cannot be read: the tools of the role are not known."""


def _check():
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import packs_check
    return packs_check


def tool_key_ok(key):
    """True when KEY is a name a tools map may hold (the rule of the review, lib/packs_check.py TOOL_KEY)."""
    return isinstance(key, str) and _check().TOOL_KEY.match(key) is not None


# --- what the runtime calls a tool

def form_of(mcp):
    """The form of a runtime's MCP tool names from the resources.mcp of its definition: {"rule", "name_key"}, or None when the definition gives no
    rule with both {server} and {tool} (the runtime has no MCP tool names qargi can write). A name_key this code does not know is kept: the shape
    of a name is still the rule's, and the names themselves cannot be worked out (part raises)."""
    if not isinstance(mcp, dict):
        return None
    rule = mcp.get("permission_rule")
    if not isinstance(rule, str) or sorted(set(PLACEHOLDER.findall(rule))) != ["server", "tool"]:
        return None
    return {"rule": rule, "name_key": mcp.get("name_key")}


def part(name_key, text):
    """A server or tool name as the runtime writes it inside the name of a tool (and inside a permission rule)."""
    if name_key is None:
        return text
    if not isinstance(name_key, str) or name_key not in NAME_KEYS:
        raise McpError("the runtime's definition writes MCP tool names by a rule this version does not know (resources.mcp.name_key %s)" % json.dumps(name_key))
    rx, to = NAME_KEYS[name_key]
    return rx.sub(to, text)


def native(form, server, tool):
    """The runtime's name of the tool TOOL of the tool pack SERVER."""
    values = {"server": part(form["name_key"], server), "tool": part(form["name_key"], tool)}
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], form["rule"])


def is_name(form, name):
    """True when NAME has the shape of the runtime's MCP tool names (the rule with any server and any tool)."""
    if not form or not isinstance(name, str):
        return False
    rx = "".join("(?:.+)" if i % 2 else re.escape(x) for i, x in enumerate(re.split(r"(\{server\}|\{tool\})", form["rule"])))
    return re.fullmatch(rx, name, re.S) is not None


def is_claimed(form, name):
    """True when NAME is a name the runtime keeps for its MCP tools: it has their shape (is_name), or it starts with the text the rule starts with
    (mcp__ under mcp__{server}__{tool}) without having it (mcp__kb, mcp____). The guard judges such a call, and no pack gives a tool that name, so it
    is refused: a name of that prefix is never passed for not being one of the runtime's MCP tool names. A rule that starts with a placeholder claims
    the names of its shape alone."""
    if is_name(form, name):
        return True
    if not form or not isinstance(name, str):
        return False
    prefix = PLACEHOLDER.split(form["rule"], 1)[0]
    return bool(prefix) and name.startswith(prefix)


# --- the packs of a role

def _load(path, what):
    try:
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError) as e:
        raise McpError("%s cannot be read (%s)" % (what, getattr(e, "strerror", None) or type(e).__name__))


def effective(conf, project, role):
    """The kind:name entries of the packs a role of a project gets, as `effective` of lib/packs.sh lists them: every pack linked at a scope that
    reaches the role, sorted, minus the role's packs_off."""
    links_file = os.path.join(conf, "packs", "links.json")
    if not os.path.exists(links_file):
        return []
    links = _load(links_file, "the links of the pack library")
    links = links.get("links") if isinstance(links, dict) else None
    if not isinstance(links, list) or not all(isinstance(x, dict) for x in links):
        raise McpError("the links of the pack library are not a list of links")
    off = []
    answers = os.path.join(conf, "projects", project + ".json")
    if os.path.isfile(answers):
        doc = _load(answers, "the answers of project %s" % project)
        roles = doc.get("roles") if isinstance(doc, dict) else None
        r = roles.get(role) if isinstance(roles, dict) else None
        off = r.get("packs_off") if isinstance(r, dict) else None
        if off is None or off is False:
            off = []
        if not isinstance(off, list):
            raise McpError("roles.%s.packs_off of project %s is not a list" % (role, project))
    got = set()
    for x in links:
        s = x.get("scope")
        if (s == "user" or (s == "user-role" and x.get("role") == role) or (s == "project" and x.get("project") == project)
                or (s == "project-role" and x.get("project") == project and x.get("role") == role)):
            if isinstance(x.get("pack"), str):
                got.add(x["pack"])
    return sorted(e for e in got if e not in off)


def tools_of(conf, project, role, form):
    """{the runtime's name: [Tool, ...]} of the tools of the tool packs ROLE of PROJECT gets on the local surface. A name with more than one Tool is
    ambiguous. A pack that is missing, changed since its approval or fails its review is there with `unusable` set on its tools (none when its file
    cannot be read as a tool pack at all)."""
    C = _check()
    packs = os.path.join(conf, "packs")
    table = {}
    for e, kind, name, skip in C.usable(effective(conf, project, role), project, "local", packs, conf):
        if kind != "tool" or skip is not None or not PACK_NAME.match(name):
            continue                                   # a pack the project's local runtime cannot use is not attached: its tools are not the role's
        p = C.item_path(packs, "tool", name)
        unusable = None
        if not os.path.isfile(p) or os.path.islink(p):
            unusable = "is linked but not in the library"
        else:
            want = C.approved_of(p)
            if not want or want != C.content_hash(p):
                unusable = "changed since it was approved (qargi tool seal %s)" % name
            elif C.review("tool", p)[1] != 0:
                unusable = "fails its review (qargi tool show %s)" % name
        doc = C.read_tool(p) if unusable != "is linked but not in the library" else None
        tools = doc.get("tools") if isinstance(doc, dict) else None
        if not isinstance(tools, dict):
            continue
        hints = C.tool_list_of(p)
        if hints is C.BAD:                             # the review failed on it (the pack is unusable); nothing in it is a declared read
            hints = {"tools": {}}
        for key, policy in tools.items():
            if not C.TOOL_KEY.match(key):
                continue
            why = None
            if policy != "always_allow":
                why = "its policy is %s, and only an always_allow tool is a declared read" % (policy if isinstance(policy, str) else "not a policy")
            elif C.write_like(key):
                why = "its name is write-like"
            elif hints is not None and hints["tools"].get(key) != "read-only":
                why = "the server's tool listing the pack was approved with does not mark it read-only (readOnlyHint)"
            table.setdefault(native(form, name, key), []).append(Tool(name, key, policy, why is None, why, unusable))
    return table


# --- a call

PLAIN_NAME = re.compile(r"[A-Za-z0-9_./:@-]+\Z")


def shown(name):
    """The name of a called tool as a message prints it: as it is when it is made of plain characters, else as a JSON string (the name comes with the
    call, and a newline or an escape in it stays on the line of the refusal)."""
    return name if isinstance(name, str) and PLAIN_NAME.match(name) else json.dumps(name, ensure_ascii=True)


def refusal(conf, project, role, read_only, name, form, table=None):
    """Why a member may not call the MCP tool NAME (the runtime's name) for ROLE of PROJECT, or None when it may. read_only: the call is made under
    the read-only class."""
    try:
        found = (tools_of(conf, project, role, form) if table is None else table).get(name, [])
    except McpError as e:
        return "%s, so the tools of the role %s of %s are not known" % (e, role, project)
    if not found:
        return ("%s is not a tool of a tool pack linked to the role %s of %s (qargi tool effective %s %s lists the packs); a member calls only the MCP "
                "tools its role was given" % (shown(name), role, project, project, role))
    if len(found) > 1:
        return ("%s stands for more than one tool of the role %s of %s (%s): the runtime writes their names the same way, so the call cannot be judged"
                % (shown(name), role, project, ", ".join("%s of pack %s" % (t.tool, t.pack) for t in found)))
    t = found[0]
    if t.unusable:
        return "the tool pack %s %s, so its tools are not available to a member" % (t.pack, t.unusable)
    if t.policy == "always_ask":
        return ("the tool %s of pack %s is always_ask: it waits for a person's answer, and a member runs unattended" % (t.tool, t.pack))
    if read_only and not t.read:
        return ("under the read-only class only a declared read of a tool pack is called, and the tool %s of pack %s is not one: %s"
                % (t.tool, t.pack, t.why_not_read))
    return None


def member_tools(conf, project, roles, read_only, form):
    """The runtime's names, sorted, of the MCP tools a member that serves ROLES of PROJECT may call for at least one of them: the tool list of the
    member. read_only: {role: True when the role is of the read-only class}. No form (a runtime with no MCP names) or no tool pack: none."""
    names = set()
    if not form:
        return []
    for role in roles:
        table = tools_of(conf, project, role, form)
        names.update(n for n in table if refusal(conf, project, role, bool(read_only.get(role)), n, form, table) is None)
    return sorted(names)
