# Good practices to use with source control (such as git)

## Merge Requests (MR)
* enable working in small batches
* 1 Merge Request should ideally cover 1 feature or 1 bug
* a proposal to incorporate changes from a source branch to a target branch
* an opportunity for another person to review the changes and leave comments
* can be Marked as draft - this means the MR is still in progress
* usually, we merge a MR when
	* someone else (other than the MR author) reviewed the changes
	* the new code passes all the tests
	* there are no git conflicts with the base branch

## Write Good Commit Messages
* Each commit should have a description that explains the why — but not necessarily the how — regarding the change.
* A good commit message makes it easier for a reviewer — and you — to understand the purpose of the commit later.  
* A good commit message references the task ID(s) that the commit addressed (if applicable).

## Ensure you're working from latest version
* often, there are many different branches in a git repository
* when multiple people push changes to a git repository, they may push to any branch they want (unless there is a rule against it, e.g. direct pushes to the `main` branch may be denied)
* It’s easy to have a local copy of the codebase fall behind the global copy. Make sure to `git pull` or `git fetch` the latest code before making updates. This will help avoid conflicts at merge time.

## Agree on a workflow
* it helps if a team of people has decided upon what git branching strategy to use
* one of the simplest ones is called `feature branches`. In this strategy we have:
	* one `main` branch. It's used for integration. The `main` branch should always be in a working state (e.g. passing all the tests).
	* multiple feature branches. Feature branches are created from the `main` branch, and developers use feature branches to add their new changes to the repository
	* the feature branches should be short-living. It is less complicated to maintain.
