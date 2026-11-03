# MediAssist – how we use Git branches (local, no GitHub needed)

## The idea
- **`main`** = the safe, working version. We never build new things directly on it.
- **A feature branch** = a copy where we try new changes (e.g. `feature/changes-v2`).
- Changes work → **merge** the branch into `main`.
- Something breaks → **switch back** to `main`. Everything is exactly as it was.

`.env` (your keys) is never saved in Git (see `.gitignore`), so it stays the same on every branch.

## Everyday commands (run in the `mediassist` folder)

| What you want | Command |
|---|---|
| See which branch you are on and what changed | `git status` |
| Save a checkpoint on the current branch | `git add -A` then `git commit -m "short message"` |
| Start new work safely | `git switch -c feature/<name>` |
| Go back to the safe version | `git switch main` |
| Go back to the work branch | `git switch feature/<name>` |
| List branches | `git branch` |
| See history | `git log --oneline --graph --all` |
| Changes are good → put them into main | `git switch main` then `git merge feature/<name>` |
| Throw away a branch that went wrong | `git switch main` then `git branch -D feature/<name>` |
| Undo uncommitted changes to one file | `git restore <file>` |

**After switching branches:** stop `python main.py` (Ctrl + C) and start it again, so the bot runs the code of that branch.

## Our routine
1. Before any new work: on `main`, everything committed (`git status` shows "nothing to commit").
2. `git switch -c feature/<what-we-are-doing>`
3. Claude writes the changes into the folder → test → `git add -A` + `git commit -m "..."` after each working step.
4. Everything tested → merge into `main` and tag it (e.g. `git tag v1.1`).

## Versions
- `v1.0` = first complete working version (27 Oct 2026): bot + dashboard + Cal.com (10 doctors) + AI features.
