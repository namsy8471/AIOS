# AIOS project instructions

## Cloud and local handoff

When switching AIOS work between Codex Cloud and a local checkout, search the connected Google Drive for the `AIOS Handoff` folder. Use the same folder in both directions.

Before handing off, upload any changes that the receiving checkout cannot fetch from GitHub. Use a Git bundle for commits available only in the current checkout and a patch for changes that are still uncommitted. Include the base commit, source branch, checks run, and the next step in a short note. Use dated filenames or subfolders so handoffs remain distinguishable. Verify the uploads before sharing the Drive links in the chat. Keep credentials and private device data out of handoffs.

When receiving a handoff, check the Drive folder first. Verify the bundle and check that the patch applies to the recorded commit before restoring them in a separate branch or worktree.
