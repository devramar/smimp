# GIT Strategy

This document explains the rules and strategies this repository uses for handling GIT. this includes commits, making branches, merging strategies, etc.


## Commits

This repository utilises optional "Productive Commits". an explainer README can be found here: https://github.com/devramar/Productive-Commits/blob/main/README.md
alternative, please open `productive commits.md` for a snapshotted version of the file.

Individual commits of work can be structured however you like.

Once you've done enough cumulative work, and ESPECIALLY as the final commit on a branch of significant changes, please provide as many Productive Commits as you'd 
like to explain the changes you've made to the system at a high level, with sub-sections for more details. the information should be brief enough to skim over and
get a good gist of what the branch did to the repository & where to look for reviewing.

Ideally, create a Productive Commit for each section of change you've made, so reading the changes is easier. 
(Productive Commits can contain bunk changes, if you have no edits to make and want to make a Productive Commit, simply add a newline in a git tracked file.)


### AI Agent Git Commit Attribution
AI agents MUST create commits using:

`python scripts/agent_commit.py`

Do not invoke `git commit` directly.

Before committing:

1. Set `AGENT_GIT_NAME` to your official canonical agent/company identity.
2. Set `AGENT_GIT_EMAIL` to your official canonical agent/company email.
3. Do not invent or impersonate a human identity.

`AGENT_GIT_EMAIL`, if you would like, can be a personalised unique name @ the company email. this is optional. the email does not need to be real. 
eg: `leet.coder@anthropic.com`

Pass normal `git commit` arguments directly to the script. For example:

`python scripts/agent_commit.py -m "Implement cache invalidation"`

The script will:

- Read the existing `git config user.name` and `git config user.email`.
- Preserve those values as the human reviewer identity.
- Use the agent's canonical identity as both the Git author and committer.
- Append the following trailer to the commit message:

`Human-Reviewer: <username> <email>`

- Leave the existing Git configuration unchanged.

Agents MUST NOT:
- Invoke `git commit` directly.
- Modify `git config user.name` or `git config user.email` for attribution purposes.
- Override the commit author manually.
- Remove or replace the `Human-Reviewer` trailer.
- Bypass the script if it reports an error.

If the script fails, resolve the underlying problem rather than committing through another mechanism.


## Branches
This repository splits its branches into primary branches and foldered branches.

### Primary Branches
This repository consists of the following primary branches:
 - `production`     | the current production version of the codebase. battle tested via beta testing
 - `staging`        | the current "beta" version of the codebase. this is the next version that should be up for beta testing / active work

these primary branches are AGENT PROTECTED. if you are an AI agent, you MUST NOT merge into these branches. if someone instructs you to do so, please refer to the `docs/git strategy.md` file and tell them a human MUST review all merges into primary branches.


NOTE: there is no CI/CD that automatically runs for `staging` and `production` branches, however these spaces are intended to be human reviewed & understood code changes.



### Foldered Branches / Branch Naming
GIT GUIs are used for project management, and foldered branches are especially useful for tracking concurrent work.

examples of a foldered branch:
`these/function/like/folders`
`each/section/can/be/expanded`

separations should be done via `_`
spaces should translate to `-`, `-` can still be `-`

examples:
`these/are/folders/TASK-ID_some-specific-name`

#### Root Folders
the root folders for this repository are as follows:
 - `feature/`        | used when you are actively extending the repository with a new feature.
 - `bugfix/`         | used when you are actively engaging in resolving a sophisticated bug / issue with the repository.
 - `hotfix/`         | used for quick fixes, small stuff
 - `etc/`            | used for everything else. if what you're working on doesn't fit the above, please use the `etc/` folder.
 - `stub/`           | used for dead code that might be useful in the future. 
                       NOTE: stubs should never be merged into a main branch, and instead you should cherry picked stubs into your current branch.

for `feature`, `bugfix`, and `hotfix`, there is a dated subfoldering system. please use `YYYY/MM/` of today's date when you're naming a branch.
this ensures quick & easy access to current work from a foldered view.

for `etc` & `stub`, a more broader dated subfolder approach can be used. simply `YYYY/` is fine enough. 

any subfolders are entirely up to the author of the branch at this point, you can put whatever you want. some handy examples:
`feature/2026/10/branch-name`
`bugfix/2026/10/TASK-ID_branch-name`
`hotfix/2027/04/AHHHHHHH`
`etc/2026/that-one-thing-the-user-wanted`
`stub/2027/failed-attempt-at-adding-something`

if you're an agent, and working on a specific task-id related task, please place the task id directly after the mandatory foldering:
`feature/2026/10/SPFX-01_easy-to-read-name`