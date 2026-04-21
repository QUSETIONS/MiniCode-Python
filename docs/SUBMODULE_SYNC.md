# MiniCode Submodule Sync Guide

## What Is Happening

If `MiniCode-Python` is mounted into the main `MiniCode` repository as a submodule, then the main repository does **not** automatically track the latest state of this repository.

It only tracks:

- one specific submodule commit

That means these two things are separate:

1. this repository receives new commits
2. the main `MiniCode` repository updates its submodule pointer to one of those commits

If step 2 has not happened yet, the main repository will still show the old state.

## The Core Rule

Submodules sync a **commit pointer**, not a whole repository.

So when someone says:

- "why didn't the main repo sync over?"

the answer is usually:

- because the main repo has not updated the submodule pointer yet

## How To Check The Current Situation

In the main `MiniCode` repository:

```bash
git submodule status
```

This shows which commit the Python submodule is currently pinned to.

If you want to inspect the submodule entry more directly:

```bash
git ls-tree HEAD
```

Look for the submodule path and its commit hash.

## How To Sync The Python Submodule In The Main Repository

From the main `MiniCode` repository:

```bash
git submodule update --init --recursive
cd <python-submodule-path>
git fetch origin
git checkout <target-commit-or-branch>
cd ..
git add <python-submodule-path>
git commit -m "Update MiniCode Python submodule"
git push
```

If the team workflow is "pin to a specific commit", use:

```bash
cd <python-submodule-path>
git fetch origin
git checkout <exact-commit>
cd ..
git add <python-submodule-path>
git commit -m "Pin MiniCode Python submodule to <exact-commit>"
git push
```

## Recommended Team Workflow

For this project, the safest workflow is:

1. finish changes in `MiniCode-Python`
2. push the Python repository first
3. copy the target commit hash
4. open the main `MiniCode` repository
5. update the submodule pointer to that exact commit
6. commit the pointer update in the main repository

That avoids the confusion of:

- "the Python repo is updated"
- but "the main repo still looks old"

because both are true until the submodule pointer changes upstream.

## Why README Confusion Happens

README confusion is common with submodules because:

- people open the Python repository and see the latest README
- then open the main repository and expect to see the same thing
- but the main repository only exposes whichever commit its submodule pointer currently references

So README mismatch is not necessarily a GitHub caching issue.
It is usually a submodule pointer issue.

## Maintainer Checklist

When updating the Python version from the main repository:

1. confirm the target commit exists in `QUSETIONS/MiniCode-Python`
2. update the submodule pointer in the main `MiniCode` repository
3. commit the pointer update
4. verify the main repo now resolves to the expected Python commit
5. only then announce that the Python version has been synced

## One-Line Summary

If the main repository did not "sync over", the likely reason is simple:

the Python repository moved forward, but the main repository's submodule pointer did not.
