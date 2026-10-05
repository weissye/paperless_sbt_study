# Paperless Git handoff

Work root: `C:\work\temp\paperless_sbt_study`.
Home root: `D:\Yeshayahu\Temp\paperless_sbt_study`.
Repository: a private, initially empty `weissye/paperless_sbt_study` repository.

## Save at work

Extract this delta into the work root after the native pilot package is installed.
Create the private repository on GitHub without a README or license. Then run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Save-Paperless-Git.ps1'
& .\scripts\Save-Paperless-Git.ps1 -Push
```

The script initializes a separate repository if needed, verifies the native
archive hash, stages explicit study directories, commits and pushes main without
force. Existing staged changes and a different origin stop the operation.
Success requires matching local HEAD and remote main, and prints
`PAPERLESS_GIT_PUSH_VERIFIED`. Git credentials are handled by Git's own login.

If Git identity is not configured, configure it using your actual name and email:
`git config --global user.name "YOUR NAME"` and
`git config --global user.email "YOUR EMAIL"`, then rerun.

Preserved: generator source, authentication/projection extensions, OpenAPI,
profiles, launch scripts, validation, experiment protocol, the original uploaded
native review archive, its SHA256 and qualification, and a portable Compose
template. Changes to local root-level deployment files are not automatically
published: the supplied versioned template defines the fresh home deployment.

Excluded: passwords, local environment files, runtime runs/projects, import/export
folders, document media, databases, Docker images and volumes. New native runs
are not silently treated as archived evidence: qualify and copy their scrubbed
review archives into evidence before saving. Ignore rules do not remove secrets
that were already committed elsewhere; the script stops on staged local secret
or runtime paths rather than rewriting history.

## Install at home

Install Git, Python with the Windows launcher, Java and Provengo, plus Docker
Desktop using Linux containers. Do not copy Docker image archives. Internet is
required for GitHub and the container registries. Clone into a new directory:

```powershell
Set-Location 'D:\Yeshayahu\Temp'
git clone 'https://github.com/weissye/paperless_sbt_study.git' 'paperless_sbt_study'
Set-Location '.\paperless_sbt_study'
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
Unblock-File '.\scripts\Start-Paperless-Local.ps1'
& .\scripts\Start-Paperless-Local.ps1
```

The installer preserves an existing `docker-compose.env`, or creates new random
session/database secrets locally. It downloads Paperless **3.2.1**, PostgreSQL
**18** and Valkey **9-alpine**, and binds the UI to **127.0.0.1:9930**.
PostgreSQL and Valkey major tags can receive upstream patch updates; this is not
a claim of byte-identical images or a restored work database. No delete/reset
commands are used. The named Compose project is `paperless-sbt-study`.

On a fresh database, open `http://127.0.0.1:9930`, create `research_admin`, and
choose a local password. Then unblock and run
`scripts\Run-Paperless-Native-Smoke.ps1 -Username research_admin`.
This creates fresh tags and fresh evidence. The archived work ids 2 and 3 are
historical observations, not home fixtures. Ordinary users and the document
relationship pilot still require their next research gate.

## Continue across computers

Before switching: preserve qualified review evidence, run Save-Paperless-Git
with `-Push`, and confirm its verified commit message. At the other computer,
use `git pull --ff-only` from a clean working tree before running tests.
If both computers have committed different changes, reconcile them explicitly;
never replace either tree or force-push merely to make a transition work.

For this fresh-state research workflow, server data stays local and tests create
new synthetic fixtures. Reproducing exact old server state would require a
separate database/media backup; it is outside this Git-only code/evidence handoff.

## Validation limits

The Git workflow was exercised against a temporary local bare remote: first
commit/push, repeat save, clone, and refusal to change a mismatched origin.
Compose structure was checked offline against the pinned upstream template.
PowerShell and live Docker installation were not executed in this Linux workspace.
The earlier native pilot did run successfully on the operator's Windows server;
the original evidence is included in this delta.

Protocol files retain their prospective registration language. The native
infrastructure gate now passed; it does not complete the planned experiment.
